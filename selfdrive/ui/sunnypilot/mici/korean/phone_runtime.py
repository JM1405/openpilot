"""UI-owned phone service with immutable, timestamped copies of runtime input.

Network workers never read a live SubMaster. Startup does not bind a socket or
write Params; a configured TLS transport can be attached explicitly by the UI.
"""
import copy
import threading
import time

from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneSettings
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_navigation import PhoneNavigation
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_road_input import PhoneRoadInput
from openpilot.selfdrive.ui.sunnypilot.mici.korean.road_status import RoadStatusMonitor
from openpilot.selfdrive.ui.sunnypilot.mici.korean.settings import SettingsController, observed

SERVICES = ('carState', 'carControl', 'selfdriveState', 'selfdriveStateSP', 'carParams', 'longitudinalPlanSP')


class Message:
  def __init__(self, data):
    self.data = data

  def to_dict(self):
    return copy.deepcopy(self.data)


class Snapshot:
  def __init__(self):
    self.services = SERVICES
    self.seen = dict.fromkeys(SERVICES, False)
    self.valid = dict.fromkeys(SERVICES, False)
    self.recv_frame = dict.fromkeys(SERVICES, -1)
    self.recv_time = dict.fromkeys(SERVICES, 0.)
    self.messages = {}

  def __getitem__(self, key):
    return Message(self.messages[key])


class RuntimeInputs:
  def __init__(self, clock=time.monotonic):
    self.clock = clock
    self.lock = threading.Lock()
    self.snapshot, self.started_frame, self.release = Snapshot(), 0, True

  def capture(self, sm, started_frame, release):
    # Called only on the UI thread, immediately after its message update.
    snapshot = Snapshot()
    for name in SERVICES:
      if name in sm.services and sm.seen[name]:
        snapshot.messages[name] = copy.deepcopy(sm[name].to_dict())
        for field in ('seen', 'valid', 'recv_frame', 'recv_time'):
          getattr(snapshot, field)[name] = getattr(sm, field)[name]
    with self.lock:
      self.snapshot, self.started_frame, self.release = snapshot, started_frame, release

  def clear(self):
    with self.lock:
      self.snapshot = Snapshot()

  def __call__(self):
    with self.lock:
      # Preserve original receive timestamps, so an idle UI cannot renew stale
      # parking permission merely by reading or copying the same messages.
      return observed(self.snapshot, self.clock(), self.started_frame, release=self.release)


class PhoneRuntime:
  def __init__(self, store, *, clock=time.monotonic):
    self.inputs = RuntimeInputs(clock)
    self.controller = SettingsController(store, self.inputs)
    self.service = PhoneSettings(self.controller, clock=clock)
    self.service.navigation = PhoneNavigation(self.service, clock=clock)
    self.service.road_input = PhoneRoadInput(self.service, clock=clock)
    self.service.road_status = RoadStatusMonitor(clock=clock)
    self.transport = None
    self.road_publisher = None
    self.network_error = ''
    self.closed = False

  def update(self, sm, started_frame=0, release=False):
    if not self.closed:
      self.inputs.capture(sm, started_frame, release)
      self.service.road_status.update()

  def attach(self, transport):
    if self.closed or self.transport is not None:
      raise RuntimeError('phone transport already attached or closed')
    self.transport = transport

  def attach_road_publisher(self):
    if self.closed or self.road_publisher is not None:
      raise RuntimeError('road publisher already attached or closed')
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_road_publisher import PhoneRoadPublisher
    from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.ipc import RoadReader
    reader = RoadReader(clock=self.service.clock)
    try:
      self.road_publisher = PhoneRoadPublisher(self.service, clock=self.service.clock)
      self.service.road_status.attach(reader)
    except Exception:
      if self.road_publisher is not None:
        self.road_publisher.close()
        self.road_publisher = None
      reader.close()
      raise

  def close(self):
    self.closed = True
    self.inputs.clear()
    with self.service.lock:
      self.service.window = self.service.pending = None
      self.service.sessions.clear()
      self.service.road_input.sample()
    if self.road_publisher is not None:
      self.road_publisher.close()
      self.road_publisher = None
    self.service.road_status.close()
    if self.transport:
      self.transport.close()
      self.transport = None
