"""UI-owned phone service with immutable, timestamped copies of runtime input.

Network workers never read a live SubMaster. Startup does not bind a socket or
write Params; a configured TLS transport can be attached explicitly by the UI.
"""
import copy
import threading
import time

from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError, PhoneSettings
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_navigation import PhoneNavigation
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_management import PhoneManagement
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_kakao import PhoneKakao
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_route import PhoneRoute
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_home import HOME_MODE, home_state
from openpilot.selfdrive.ui.sunnypilot.mici.korean.road_status import RoadStatusMonitor
from openpilot.selfdrive.ui.sunnypilot.mici.korean.settings import SettingsController, observed

SERVICES = ('carState', 'carControl', 'selfdriveState', 'selfdriveStateSP', 'carParams', 'longitudinalPlanSP',
            'deviceState', 'modelManagerSP', 'pandaStates')


class UnavailableRoadInput:
  """release-mici adapter: navigation/phone management must not require road IPC."""
  def __init__(self, service):
    self.service = service

  def accept(self, token, csrf, *_):
    self.service.authorize_write(token, csrf)
    raise PhoneError('이 후보에는 도로 입력 서비스가 연결되지 않았어', 'unavailable', 404)

  def sample(self):
    return None

  def view(self):
    return {'status': 'unavailable', 'valid': False, 'uncertainty_ms': 0., 'scope': 'not_connected'}


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
        data = [item.to_dict() for item in sm[name]] if name == 'pandaStates' else sm[name].to_dict()
        snapshot.messages[name] = copy.deepcopy(data)
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

  def management(self):
    with self.lock:
      snapshot = copy.deepcopy(self.snapshot)
      started_frame = self.started_frame
    now = self.clock()
    result = {}
    for name in ('deviceState', 'modelManagerSP'):
      if (snapshot.seen.get(name) and snapshot.valid.get(name) and snapshot.recv_frame.get(name, -1) >= started_frame and
          -.01 <= now - snapshot.recv_time.get(name, 0.) <= (2.5 if name == 'modelManagerSP' else 1.5)):
        result[name] = snapshot.messages.get(name)
    if (snapshot.seen.get('carParams') and snapshot.valid.get('carParams') and
        snapshot.recv_frame.get('carParams', -1) >= started_frame):
      result['carParams'] = snapshot.messages.get('carParams')
    result['fresh'] = 'modelManagerSP' in result
    return result

  def home(self):
    with self.lock:
      return home_state(self.snapshot, self.clock(), self.started_frame)


class PhoneRuntime:
  def __init__(self, store, *, clock=time.monotonic, allow_model_change=False, allow_settings_change=True):
    self.inputs = RuntimeInputs(clock)
    self.controller = SettingsController(store, self.inputs, write_enabled=allow_settings_change)
    self.service = PhoneSettings(self.controller, clock=clock, home_check=self.home_check)
    self.controller.write_guard = self.service.write_block_reason
    self.service.management = PhoneManagement(store, self.controller, self.inputs.management,
                                               allow_model_change=allow_model_change, write_guard=self.service.write_block_reason)
    self.service.navigation = PhoneNavigation(self.service, clock=clock)
    self.service.kakao = PhoneKakao(self.service, clock=clock)
    self.service.route = PhoneRoute(self.service, clock=clock)
    try:
      from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.runtime import enabled
      if not enabled():
        raise ImportError('road input disabled')
      from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_road_input import PhoneRoadInput
      self.service.road_input = PhoneRoadInput(self.service, clock=clock)
      self.road_input_available = True
    except ImportError:
      self.service.road_input = UnavailableRoadInput(self.service)
      self.road_input_available = False
    self.service.road_status = RoadStatusMonitor(clock=clock)
    self.transport = None
    self.road_publisher = None
    self.network_error = ''
    self.closed = False

  def update(self, sm, started_frame=0, release=False):
    with self.service.lock:
      if not self.closed:
        # A gap in UI updates must revoke before fresh input can hide the gap.
        self.service._expire()
        self.inputs.capture(sm, started_frame, release)
        self.service._expire()
        self.service.road_status.update()

  def home_check(self):
    if self.closed or self.road_publisher is not None:
      return '도로 전달을 끈 수신 전용 런타임이 필요해'
    return self.inputs.home()

  def attach(self, transport):
    if self.closed or self.transport is not None:
      raise RuntimeError('phone transport already attached or closed')
    self.transport = transport

  def attach_road_publisher(self):
    with self.service.lock:
      self._attach_road_publisher()

  def _attach_road_publisher(self):
    if not self.road_input_available:
      raise RuntimeError('road input is disabled')
    if self.service.mode == HOME_MODE:
      raise RuntimeError('home reception cannot publish road input')
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
    with self.service.lock:
      self.closed = True
      self.inputs.clear()
      self.service.close()
      self.service.road_input.sample()
    if self.road_publisher is not None:
      self.road_publisher.close()
      self.road_publisher = None
    self.service.road_status.close()
    if self.transport:
      self.transport.close()
      self.transport = None
