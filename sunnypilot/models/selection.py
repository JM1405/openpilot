"""Shared phone/manager selection transaction. No model execution or vehicle commands."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import re
import threading

REQUEST = 'KoranipilotModelRequest'
RESULT = 'KoranipilotModelResult'
_memory_lock = threading.RLock()

@contextmanager
def selection_lock(params):
  # In-memory test stores have no persistent directory. Real Params always does.
  if not hasattr(params, 'get_param_path'):
    with _memory_lock:
      yield
    return
  path = Path(params.get_param_path()).parent / '.koranipilot-model.lock'
  with path.open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
      yield
    finally:
      fcntl.flock(lock, fcntl.LOCK_UN)


def bundle_signature(raw):
  raw = raw.to_dict() if hasattr(raw, 'to_dict') else raw
  # Status/progress changes do not change the identity of a catalogue entry.
  data = {k: raw.get(k) for k in ('ref', 'index', 'generation', 'runner', 'minimumSelectorVersion', 'overrides')}
  data['models'] = [{k: m.get(k) for k in ('type',)} | {
    k: {a: m.get(k, {}).get(a) for a in ('fileName', 'downloadUri')}
    for k in ('artifact', 'metadata')} for m in raw.get('models', [])]
  return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def artifact_manifest(bundle):
  result = {}
  for model in bundle.models:
    for artifact in (model.metadata, model.artifact):
      name = artifact.fileName
      if not name:
        continue
      if Path(name).name != name or name in ('.', '..') or not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
        raise ValueError('Invalid model artifact filename')
      digest = artifact.downloadUri.sha256.lower()
      if not re.fullmatch(r'[a-f0-9]{64}', digest) or not artifact.downloadUri.uri:
        raise ValueError('Missing model artifact hash or URL')
      if name in result and result[name] != digest:
        raise ValueError('Conflicting artifact identities')
      result[name] = digest
  if not result:
    raise ValueError('Empty model bundle')
  return result


class ParkedDownloadGuard:
  """Fresh vehicle truth, independent of the phone's request/approval snapshot."""
  def __init__(self, params):
    from cereal import messaging
    self.params = params
    self.sm = messaging.SubMaster(['deviceState', 'carState', 'carControl', 'selfdriveState', 'selfdriveStateSP'])
    self.started_frame = 0
    self.started = False

  def __call__(self):
    import time
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.settings import observed, sample
    self.sm.update(0)
    now = time.monotonic()
    device = sample(self.sm, 'deviceState', now, self.started_frame, static=True)
    if now - self.sm.recv_time.get('deviceState', 0.) > 1.5:
      device = None
    started = bool(device and device.get('started') and self.params.get('IsOnroad') is True)
    if started and not self.started:
      self.started_frame = self.sm.frame
    self.started = started
    return started and observed(self.sm, now, self.started_frame)['parked']
