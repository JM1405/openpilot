"""Manager-owned road derivation service. GPS auth remains with the native phone UI.

Never imports vehicle control or publishes carControl/Params. Only a configured,
read-only dataset and recent same-device GPS IPC can produce road constraints.
"""

import os
import signal
import threading
import time
from dataclasses import replace

from .ipc import LocationReader, RoadPublisher
from .live import LiveRoadAdapter
from .offline import OfflineProvider
from .dataset import DatasetInfo, inspect_snapshot, signature
from .runtime import enabled


class RoadInputService:
  def __init__(self, dataset, *, clock=time.monotonic, reader=None, publisher=None, today=None):
    self.dataset, self.clock, self.today = dataset, clock, today
    self.reader = reader if reader is not None else LocationReader(clock=clock)
    try:
      self.publisher = publisher if publisher is not None else RoadPublisher(clock=clock)
    except Exception:
      self.reader.close()
      raise
    self.store = self.adapter = None
    self.retry_at = 0.0
    self.status = "starting"
    self.closed = False
    self.file_signature = self.blocked_inode = None
    self.loaded_at = 0.
    self.dataset_info = DatasetInfo()
    self._load()

  def _drop(self, state, status):
    if self.store is not None:
      self.store.close()
    self.store = self.adapter = None
    self.file_signature = None
    self.status = status
    self.dataset_info = DatasetInfo(state, revision=self.dataset_info.revision + 1)

  def _publish(self, road=None):
    deadline = self.reader.deadline if road is not None else 0
    hint = getattr(self.reader, 'route_hint', None)
    if road is not None and hint is not None and hint.state == 'active':
      deadline = min(deadline, int(hint.valid_until*1e9))
    self.publisher.publish(road, self.status, deadline, dataset=self.dataset_info)

  def _sample(self):
    sample = self.reader.sample()
    if sample.fix is not None and sample.fix.observed_at - sample.uncertainty_ns / 1e9 <= self.loaded_at:
      return replace(sample, fix=None, valid_until_ns=0, status='waitingForFreshFix')
    return sample

  def _load(self):
    self.dataset_info = DatasetInfo('loading', revision=self.dataset_info.revision)
    self.status = 'datasetLoading'
    self._publish()
    try:
      self.store, self.file_signature, self.dataset_info = inspect_snapshot(self.dataset, self.dataset_info.revision)
      self.loaded_at = self.clock()
      kwargs = {} if self.today is None else {'today': self.today}
      self.adapter = LiveRoadAdapter(self._sample, OfflineProvider(self.store), route=lambda: getattr(self.reader, 'route_hint', None), **kwargs)
      self.status = 'waitingForFreshFix'
    except Exception as exc:
      self._drop('missing' if isinstance(exc, FileNotFoundError) else 'invalid', 'datasetUnavailable')
      self.retry_at = self.clock() + 5.
    self._publish()

  def _changed(self, current):
    if current == self.file_signature:
      return False
    if current[:2] == self.file_signature[:2]:
      self.blocked_inode = current[:2]
      self._drop('invalid', 'datasetModifiedInPlace')
    else:
      self._drop('loading', 'datasetChanged')
      self.retry_at = 0.
    return True

  def tick(self):
    if self.closed:
      return
    now = self.clock()
    try:
      current = signature(self.dataset)
    except (OSError, ValueError) as exc:
      state = 'missing' if isinstance(exc, FileNotFoundError) else 'invalid'
      if self.store is not None or self.dataset_info.state != state:
        if isinstance(exc, ValueError) and self.file_signature is not None:
          self.blocked_inode = self.file_signature[:2]
        self._drop(state, 'datasetUnavailable')
      self.reader.sample()
      self._publish()
      return
    if self.store is not None and self._changed(current):
      self._publish()
      return
    if self.store is None:
      if current[:2] == self.blocked_inode:
        self.status = 'datasetModifiedInPlace'
      elif now >= self.retry_at:
        self.blocked_inode = None
        self._load()
      self.reader.sample()
      self._publish()
      return
    road = None
    if self.adapter is not None:
      try:
        road = self.adapter(now)
        self.status = self.adapter.observation.status
        if road is not None and self.clock() * 1e9 >= self.reader.deadline:
          road, self.status = None, "derivationExpired"
      except Exception:
        # SQLite errors revoke this output, then reopen on a bounded retry.
        self._drop('invalid', 'providerError')
        self.retry_at = now + 5.0
    else:
      self.reader.sample()  # Drain latest packet even while the dataset is absent.
    if road is not None:
      try:
        if self._changed(signature(self.dataset)):
          road = None
      except (OSError, ValueError):
        if self.file_signature is not None:
          self.blocked_inode = self.file_signature[:2]
        self._drop('invalid', 'datasetUnavailable')
        road = None
    self._publish(road)

  def close(self):
    if self.closed:
      return
    self.closed = True
    try:
      self.status = 'roadServiceStopped'
      self._publish()
    finally:
      if self.store is not None:
        self.store.close()
      self.reader.close()
      self.publisher.close()


def main():
  if not enabled():
    return
  stop = threading.Event()

  def shutdown(signum, frame):
    stop.set()

  for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, shutdown)
  service = RoadInputService(os.environ.get("KOREAN_ROAD_DATASET", ""))
  try:
    while not stop.is_set():
      service.tick()
      stop.wait(0.05)
  finally:
    service.close()


if __name__ == "__main__":
  main()
