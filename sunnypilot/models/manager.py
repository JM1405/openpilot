"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

import asyncio
import os
import time
import tempfile
import shutil
from pathlib import Path

import aiohttp
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware.hw import Paths

from cereal import messaging, custom
from openpilot.sunnypilot.models.fetcher import ModelFetcher
from openpilot.sunnypilot.models.helpers import get_active_bundle, validate_active_bundle, verify_file
from openpilot.sunnypilot.models.selection import REQUEST, RESULT, selection_lock, bundle_signature, artifact_manifest, ParkedDownloadGuard


class ModelManagerSP:
  """Manages model downloads and status reporting"""

  def __init__(self, params=None, publisher=None, parked=None):
    self.params = Params() if params is None else params
    self.model_fetcher = ModelFetcher(self.params)
    self.pm = messaging.PubMaster(["modelManagerSP"]) if publisher is None else publisher
    self.download_allowed = ParkedDownloadGuard(self.params) if parked is None else parked
    self._request = None
    self._index = None
    self._active_raw = None
    self._cache_path = None
    self._last_fetch = -60.
    self.available_models: list[custom.ModelManagerSP.ModelBundle] = []
    self.selected_bundle: custom.ModelManagerSP.ModelBundle = None
    self.active_bundle: custom.ModelManagerSP.ModelBundle = get_active_bundle(self.params)
    self._chunk_size = 128 * 1000  # 128 KB chunks
    self._download_start_times: dict[str, float] = {}  # Track start time per model

  def _sync_artifact_progress(self, source_artifact) -> None:
    """Mirror download progress to all artifacts sharing the same filename in the selected bundle."""
    if not self.selected_bundle:
      return
    for model in self.selected_bundle.models:
      for artifact in (model.artifact, model.metadata):
        if artifact is not source_artifact and artifact.fileName == source_artifact.fileName:
          artifact.downloadProgress.status = source_artifact.downloadProgress.status
          artifact.downloadProgress.progress = source_artifact.downloadProgress.progress
          artifact.downloadProgress.eta = source_artifact.downloadProgress.eta

  def _calculate_eta(self, filename: str, progress: float) -> int:
    """Calculate ETA based on elapsed time and current progress"""
    if filename not in self._download_start_times or progress <= 0:
      return 60  # Default ETA for new downloads

    elapsed_time = time.monotonic() - self._download_start_times[filename]
    if elapsed_time <= 0:
      return 60

    # If we're at X% after Y seconds, we can estimate total time as (Y / X) * 100
    total_estimated_time = (elapsed_time / progress) * 100
    eta = total_estimated_time - elapsed_time

    return max(1, int(eta))  # Return at least 1 second if download is ongoing

  async def _download_file(self, url: str, path: str, model) -> None:
    """Downloads a file with progress tracking"""
    self._download_start_times[model.fileName] = time.monotonic()

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1800, sock_connect=15, sock_read=15)) as session:
      async with session.get(url) as response:
        response.raise_for_status()
        total_size = int(response.headers.get("content-length", 0))
        bytes_downloaded = 0

        with open(path, 'wb') as f:
          async for chunk in response.content.iter_chunked(self._chunk_size):  # type: bytes
            self._check_request()
            f.write(chunk)
            bytes_downloaded += len(chunk)

            if total_size > 0:
              progress = (bytes_downloaded / total_size) * 100
              model.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.downloading
              model.downloadProgress.progress = progress
              model.downloadProgress.eta = self._calculate_eta(model.fileName, progress)
              self._sync_artifact_progress(model)
              self._report_status()

        # Clean up start time after download completes
        del self._download_start_times[model.fileName]

  async def _download_chunked(self, base_url: str, base_path: str, artifact) -> None:
    from openpilot.common.file_chunker import get_manifest_path, get_chunk_name
    manifest_url = get_manifest_path(base_url)
    manifest_path = get_manifest_path(base_path)

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1800, sock_connect=15, sock_read=15)) as session:
      async with session.get(manifest_url) as resp:
        if resp.status == 404:
          raise FileNotFoundError
        resp.raise_for_status()
        num_chunks = int((await resp.read()).strip())
        if not 1 <= num_chunks <= 4096:
          raise ValueError("Invalid chunk count")
        self._check_request()

    self._download_start_times[artifact.fileName] = time.monotonic()

    for i in range(num_chunks):
      chunk_url = get_chunk_name(base_url, i, num_chunks)
      chunk_path = get_chunk_name(base_path, i, num_chunks)
      chunk_downloaded = 0
      async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1800, sock_connect=15, sock_read=15)) as session:
        async with session.get(chunk_url) as response:
          response.raise_for_status()
          chunk_size = int(response.headers.get("content-length", 0))
          with open(chunk_path, 'wb') as f:
            async for data in response.content.iter_chunked(self._chunk_size):
              self._check_request()
              f.write(data)
              chunk_downloaded += len(data)
              intra = chunk_downloaded / max(chunk_size, 1)
              progress = min(99, (i + intra) / num_chunks * 100)
              artifact.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.downloading
              artifact.downloadProgress.progress = progress
              artifact.downloadProgress.eta = self._calculate_eta(artifact.fileName, progress)
              self._sync_artifact_progress(artifact)
              self._report_status()

    with open(manifest_path, 'w') as f:
      f.write(str(num_chunks))
    if os.path.isfile(base_path):
      os.remove(base_path)
    del self._download_start_times[artifact.fileName]

  async def _process_artifact(self, artifact, destination_path: str) -> None:
    if not artifact.downloadUri.uri:
      return None

    url = artifact.downloadUri.uri
    expected_hash = artifact.downloadUri.sha256
    filename = artifact.fileName
    full_path = os.path.join(destination_path, filename)

    try:
      self._check_request()
      cached_path = os.path.join(self._cache_path, filename)
      if await verify_file(cached_path, expected_hash) or await verify_file(full_path, expected_hash):
        artifact.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.cached
        artifact.downloadProgress.progress = 100
        artifact.downloadProgress.eta = 0
        self._sync_artifact_progress(artifact)
        self._report_status()
        return

      try:
        await self._download_chunked(url, full_path, artifact)
      except FileNotFoundError:
        await self._download_file(url, full_path, artifact)

      if not await verify_file(full_path, expected_hash):
        raise ValueError(f"Hash validation failed for {filename}")

      # Normalize chunked downloads to a single verified file before atomic promotion.
      from openpilot.common.file_chunker import get_existing_chunks
      parts = get_existing_chunks(full_path)
      if len(parts) > 1:
        with open(full_path, 'wb') as output:
          for part in parts[1:]:
            with open(part, 'rb') as source:
              shutil.copyfileobj(source, output)
        for part in parts:
          os.remove(part)
      self._check_request()
      artifact.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.downloaded
      artifact.downloadProgress.progress = 100
      artifact.downloadProgress.eta = 0
      self._sync_artifact_progress(artifact)
      self._report_status()

    except Exception as e:
      cloudlog.error(f"Error downloading {filename}: {str(e)}")
      # Only the private staging directory is discarded by the transaction.
      artifact.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.failed
      artifact.downloadProgress.eta = 0
      self._sync_artifact_progress(artifact)
      self.selected_bundle.status = custom.ModelManagerSP.DownloadStatus.failed
      self._report_status()
      self._download_start_times.pop(artifact.fileName, None)
      raise

  async def _process_model(self, model, destination_path: str) -> None:
    """Processes a single model download including verification"""
    model_artifact = model.artifact
    metadata_artifact = model.metadata

    await self._process_artifact(metadata_artifact, destination_path)
    await self._process_artifact(model_artifact, destination_path)

  def _report_status(self) -> None:
    """Reports current status through messaging system"""
    msg = messaging.new_message('modelManagerSP', valid=True)
    model_manager_state = msg.modelManagerSP
    if self.selected_bundle:
      model_manager_state.selectedBundle = self.selected_bundle

    if self.active_bundle:
      model_manager_state.activeBundle = self.active_bundle

    model_manager_state.availableBundles = self.available_models
    self.pm.send('modelManagerSP', msg)

  def _same_request(self):
    return (self.params.get("ModelManager_DownloadIndex") == self._index
            and self.params.get(REQUEST) == self._request)

  def _check_request(self):
    if not self._same_request():
      raise RuntimeError("Model request cancelled or replaced")
    if not self.download_allowed():
      raise RuntimeError("Model download requires fresh parked/disengaged vehicle state")
    if self.params.get("ModelManager_ActiveBundle") != self._active_raw:
      raise RuntimeError("Configured model changed during download")

  async def _download_bundle(self, model_bundle, destination_path):
    """Verify privately, then commit only the still-current parked request.

    A failed/interrupted download never removes or overwrites an active artifact.
    The existing bundle remains configured until every new artifact is verified.
    """
    with selection_lock(self.params):
      self._request = self.params.get(REQUEST)
      self._index = model_bundle.index
      self._active_raw = self.params.get("ModelManager_ActiveBundle")
      self._cache_path = destination_path
      self._check_request()
      if self._request is not None and (not isinstance(self._request, dict) or
          self._request.get('ref') != model_bundle.ref or self._request.get('index') != model_bundle.index or
          self._request.get('signature') != bundle_signature(model_bundle)):
        raise ValueError("Model catalogue changed; select the model again")
      manifest = artifact_manifest(model_bundle)
      active = get_active_bundle(self.params)
      active_manifest = artifact_manifest(active) if active is not None else {}
      if any(name in active_manifest and active_manifest[name] != digest for name, digest in manifest.items()):
        raise ValueError("Artifact filename conflicts with the configured model")

    self.selected_bundle = model_bundle.as_builder() if hasattr(model_bundle, 'as_builder') else model_bundle
    self.selected_bundle.status = custom.ModelManagerSP.DownloadStatus.downloading
    os.makedirs(destination_path, exist_ok=True)
    try:
      with tempfile.TemporaryDirectory(prefix='.download-', dir=destination_path) as staging:
        seen = set()
        for model in self.selected_bundle.models:
          for artifact in (model.metadata, model.artifact):
            if artifact.fileName and artifact.fileName not in seen:
              seen.add(artifact.fileName)
              await self._process_artifact(artifact, staging)
        with selection_lock(self.params):
          self._check_request()
          # Files with an active filename can only have the identical hash.
          # A crash during promotion leaves the old bundle selected and usable.
          for path in Path(staging).iterdir():
            # Old chunk manifests take precedence in the loader; remove only
            # this non-active cache entry's manifest before installing its file.
            old_manifest = Path(destination_path) / (path.name + '.chunkmanifest')
            if old_manifest.exists():
              old_manifest.unlink()
            os.replace(path, Path(destination_path) / path.name)
          self._check_request()
          self.selected_bundle.status = custom.ModelManagerSP.DownloadStatus.downloaded
          self.params.put("ModelManager_ActiveBundle", self.selected_bundle.to_dict(), block=True)
          self.active_bundle = self.selected_bundle
          self._finish('ready', '다운로드 완료 · 다음 기동에서 실행 확인')
    finally:
      self.selected_bundle = None
      self._report_status()

  def _finish(self, state, message):
    # Caller holds the shared selection lock. Never clear a newer request.
    if not self._same_request():
      return
    request = self._request if isinstance(self._request, dict) else {}
    self.params.put(RESULT, {'state': state, 'message': message,
                            'id': request.get('id'), 'ref': request.get('ref')}, block=True)
    self.params.remove("ModelManager_DownloadIndex")
    self.params.remove(REQUEST)

  def download(self, model_bundle, destination_path):
    asyncio.run(self._download_bundle(model_bundle, destination_path))

  def run_once(self, destination_path=None):
    offroad = self.params.get("IsOnroad") is False
    parked = self.download_allowed()
    # Catalogue/status remain available while ignition is on. Download and
    # selection commit require fresh P, standstill, and all assistance inactive.
    if (offroad or parked) and time.monotonic() - self._last_fetch >= 60:
      self._last_fetch = time.monotonic()
      self.available_models = self.model_fetcher.get_available_bundles()
    elif not self.available_models:
      cached, _ = self.model_fetcher.model_cache.get()
      self.available_models = self.model_fetcher.model_parser.parse_models(cached)
    if offroad:
      with selection_lock(self.params):
        if self.params.get("IsOnroad") is False:
          validate_active_bundle(self.params)
    self.active_bundle = get_active_bundle(self.params)
    if parked:
      with selection_lock(self.params):
        self._index = self.params.get("ModelManager_DownloadIndex")
        self._request = self.params.get(REQUEST)
      if self._index is not None:
        bundle = next((m for m in self.available_models if m.index == self._index), None)
        try:
          if bundle is None:
            raise ValueError("Requested model is no longer in the catalogue")
          self.download(bundle, destination_path or Paths.model_root())
        except Exception as e:
          cloudlog.exception(e)
          with selection_lock(self.params):
            if self.download_allowed():
              self._finish('failed', '다운로드 실패 · 기존 모델 유지 · 모델을 다시 선택해 줘')
          self.selected_bundle = None
    if offroad:
      with selection_lock(self.params):
        if self.params.get("IsOnroad") is False and self.params.get("ModelManager_ClearCache"):
          self.active_bundle = get_active_bundle(self.params)
          self.clear_model_cache()
          self.params.remove("ModelManager_ClearCache")
    self._report_status()

  def main_thread(self):
    rk = Ratekeeper(1, print_delay_threshold=None)
    while True:
      try:
        self.run_once()
      except Exception as e:
        cloudlog.exception(f"Error in main thread: {e}")
      rk.keep_time()

  def clear_model_cache(self) -> None:
    """
    Clears the model cache directory of all files except those in the active model bundle.
    """

    # Get list of files used by active model bundle
    active_files = []
    if self.active_bundle is not None: # When the default model is active
      for model in self.active_bundle.models:
        if hasattr(model, 'artifact') and model.artifact.fileName:
          active_files.append(model.artifact.fileName)
        if hasattr(model, 'metadata') and model.metadata.fileName:
          active_files.append(model.metadata.fileName)

    # Remove all files except active ones (including their chunk files)
    model_dir = Paths.model_root()
    try:
      for filename in os.listdir(model_dir):
        base = filename.split('.chunk')[0] if '.chunk' in filename else filename
        if base not in active_files and filename not in active_files:
          file_path = os.path.join(model_dir, filename)
          if os.path.isfile(file_path):
            os.remove(file_path)
      cloudlog.info("Model cache cleared, keeping active model files")
    except Exception as e:
      cloudlog.exception(f"Error clearing model cache: {str(e)}")

def main():
  ModelManagerSP().main_thread()


if __name__ == "__main__":
  main()
