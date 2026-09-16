"""One UI-process publication worker, independent of whether the settings page is visible."""

import threading
import time
from dataclasses import replace

from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.ipc import LocationPublisher


class PhoneRoadPublisher:
  def __init__(self, service, *, clock=time.monotonic):
    self.service = service
    self.publisher = LocationPublisher(clock=clock)
    self.stop = threading.Event()
    self.thread = threading.Thread(target=self.run, name="phone-road-ipc", daemon=True)
    try:
      self.thread.start()
    except Exception:
      self.publisher.close()
      raise

  def run(self):
    try:
      while not self.stop.is_set():
        # Sampling rechecks auth expiration/revocation. Never hold the auth lock
        # during IPC send or dataset access.
        self.publisher.publish(self.service.road_input.sample())
        self.stop.wait(0.05)
    finally:
      try:
        sample = self.service.road_input.sample()
        self.publisher.publish(
          replace(
            sample, revision=sample.revision + 1, generation=sample.generation + 1, status="phoneServiceStopped", fix=None, valid_until_ns=0, uncertainty_ns=0
          )
        )
      finally:
        self.publisher.close()

  def close(self):
    self.stop.set()
    self.thread.join(timeout=1.0)
