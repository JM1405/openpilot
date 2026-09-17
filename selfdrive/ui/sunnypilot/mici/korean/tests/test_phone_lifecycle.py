"""Exercise production UI loop/lifecycle code with a virtual clock and hardware doubles.

No renderer, device, CAN or real publisher is used. The real render generator,
UI main loop, UIState update and native phone owner supply the scheduling.
"""
import ast
import copy
import os
from pathlib import Path
import types
import unittest  # noqa: TID251
from unittest.mock import Mock, patch  # noqa: TID251

from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_home import HomeSM
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_management import Store

ROOT = Path(__file__).resolve().parents[6]


def source_definition(path, name, scope, methods=None):
  path = ROOT / path
  node = next(n for n in ast.parse(path.read_text()).body if getattr(n, 'name', None) == name)
  if methods is not None:
    node.bases = []
    node.body = [n for n in node.body if getattr(n, 'name', None) in methods]
  future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
  module = ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[]))
  exec(compile(module, str(path), 'exec'), scope)
  return scope[name]


class PhoneLifecycleTest(unittest.TestCase):
  def setUp(self):
    self.now = 100.
    self.store = Store()
    self.store.get_bool = lambda key: bool(self.store.get(key))
    self.sm = HomeSM(self.now)
    self.sm.frame = 11
    self.template = copy.deepcopy(self.sm.data)
    self.stopped = set()
    self.gui = types.SimpleNamespace(
      _profile_render_frames=0, _window_close_requested=False, _should_render=True, _target_fps=20,
      _mouse=types.SimpleNamespace(get_events=list), _render_texture=None, _scale=1.,
      _nav_stack_ticks=[], _nav_stack=[], _nav_stack_widgets_to_render=1,
      _show_fps=False, _show_touches=False, _show_mouse_coords=False, _grid_size=0, _frame=0,
      _monitor_fps=lambda: None, init_window=lambda _: None, width=536, height=240,
    )
    clock = types.SimpleNamespace(monotonic=lambda: self.now, sleep=lambda _: None)
    ray = Mock()
    ray.window_should_close.return_value = False
    ray.get_frame_time.return_value = .05
    gui_cls = source_definition('system/ui/lib/application.py', 'GuiApplication',
      {'time': clock, 'rl': ray, 'PC': False, 'RECORD': False},
      {'render', 'add_nav_stack_tick', 'remove_nav_stack_tick'})
    for name in ('render', 'add_nav_stack_tick', 'remove_nav_stack_tick'):
      setattr(self.gui, name, types.MethodType(getattr(gui_cls, name), self.gui))

    class StateSP:
      def __init__(self): self.sm_services_ext = []
      def update(self): pass
    ui_cls = source_definition('selfdrive/ui/ui_state.py', 'UIState', {
      'UIStateSP': StateSP, 'Params': lambda: self.store,
      'messaging': types.SimpleNamespace(SubMaster=lambda _: self.sm),
      'PrimeState': lambda: types.SimpleNamespace(start=lambda: None),
      'UIStatus': types.SimpleNamespace(DISENGAGED='disengaged'),
      'log': types.SimpleNamespace(PandaState=types.SimpleNamespace(PandaType=types.SimpleNamespace(unknown=0)),
                                  LongitudinalPersonality=types.SimpleNamespace(standard=1)),
      'device': types.SimpleNamespace(update=lambda: None),
    })
    self.ui = ui_cls()
    self.ui._params_thread = object()
    self.ui._update_state = lambda: None
    self.ui._update_status = lambda: None
    self.ui.is_sp_release = True
    self.sm.update = self.feed_publishers

    class Base:
      def __init__(self):
        self._network_panel = types.SimpleNamespace(connected_wifi_ipv4='')
        items = []
        self._scroller = types.SimpleNamespace(_items=items, add_widget=items.append)
    root_cls = source_definition('selfdrive/ui/sunnypilot/mici/korean/native_settings.py', 'PhoneSettingsRoot',
      {'DrivingSettingsRoot': Base, 'os': os, 'ui_state': self.ui, 'gui_app': self.gui,
       'atexit': types.SimpleNamespace(register=lambda _: None)})
    modules = {'openpilot.selfdrive.ui.sunnypilot.mici.korean.native_phone':
               types.SimpleNamespace(KoreanPhoneButton=lambda _: object())}
    with patch.dict(os.environ, KOREAN_PHONE_LOCAL='0', KOREAN_PHONE_CERT='', KOREAN_ROAD_INPUT='0'), patch.dict('sys.modules', modules):
      self.root = root_cls()
    self.addCleanup(self.root.close_phone)
    self.runtime = self.root.phone_runtime
    self.runtime.inputs.clock = lambda: self.now
    self.runtime.service.clock = lambda: self.now
    self.runtime.update(self.sm)
    self.service = self.runtime.service
    self.connect()

  def connect(self):
    self.service.device_set_home(True)
    ticket = self.service.pair(self.service.device_open()['window']['code'], 'Lifecycle test')
    self.service.device_decide(self.service.pending['id'], True)
    self.token = self.service.status(ticket)[1]

  def tearDown(self):
    self.assertEqual(self.store.writes, [])

  def feed_publishers(self, _):
    self.sm.frame += 1
    # Independent 2 Hz device and 10 Hz panda schedules, with a 20 Hz UI.
    for name, period in (('deviceState', .5), ('pandaStates', .1)):
      if name not in self.stopped and self.now - self.sm.recv_time[name] >= period - 1e-8:
        self.sm.feed(name, self.template[name], self.now)
        self.sm.recv_frame[name] = self.sm.frame

  def run_ui(self, frames, screen_on=False):
    self.gui._should_render = screen_on
    render = self.gui.render
    def finite_render():
      loop = render()
      try:
        for _ in range(frames):
          self.now = round(self.now + .05, 6)
          yield next(loop)
      finally:
        loop.close()
    self.gui.render = finite_render
    main = source_definition('selfdrive/ui/ui.py', 'main', {
      'gui_app': self.gui, 'ui_state': self.ui, 'time': types.SimpleNamespace(monotonic=lambda: self.now),
      'BIG_UI': False, 'TICI': False, 'MiciMainLayout': lambda: None,
      'Priority': types.SimpleNamespace(CTRL_HIGH=1), 'config_realtime_process': lambda *_: None,
      'messaging': types.SimpleNamespace(PubMaster=lambda _: Mock(), new_message=lambda _: Mock()),
    })
    try:
      main()
    finally:
      self.gui.render = render

  def test_screen_off_keeps_fresh_telemetry_and_approved_session(self):
    self.run_ui(100)
    self.assertEqual(self.sm.recv_time['deviceState'], self.now)
    self.assertEqual(self.runtime.inputs.snapshot.recv_time['deviceState'], self.now)
    self.assertTrue(self.service.mode_view()['home_active'])
    self.service.session(self.token)

  def test_navigation_depth_screen_off_and_wake_keep_same_session(self):
    for depth, screen_on in ((1, True), (4, True), (0, False), (2, True)):
      self.gui._nav_stack = [Mock() for _ in range(depth)]
      self.run_ui(50, screen_on=screen_on)
      self.service.session(self.token)
      self.assertTrue(self.service.home_active)

  def test_missing_real_publisher_still_revokes_with_ui_running(self):
    for name in ('deviceState', 'pandaStates'):
      with self.subTest(name=name):
        self.stopped = {name}
        self.run_ui(31)
        self.assertFalse(self.service.home_active)
        with self.assertRaises(PhoneError):
          self.service.session(self.token)
        self.stopped.clear()
        self.run_ui(20)
        self.assertFalse(self.service.home_active)  # no automatic reapproval
        self.connect()

  def test_entire_ui_stall_revokes_before_fresh_input_can_hide_gap(self):
    self.now += 2.
    self.run_ui(1)
    self.assertFalse(self.service.home_active)
    with self.assertRaises(PhoneError):
      self.service.session(self.token)

  def test_ignition_revokes_while_screen_off(self):
    self.template['pandaStates'][0]['ignitionLine'] = True
    self.run_ui(3)
    self.assertFalse(self.service.home_active)
    self.assertIn('점화', self.service.home_error)

  def test_owner_close_unregisters_and_cannot_restore_session(self):
    self.root.close_phone()
    self.root.close_phone()
    self.run_ui(40)
    self.assertEqual(self.runtime.inputs.snapshot.messages, {})
    self.assertEqual(self.service.sessions, {})
    self.assertTrue(self.runtime.closed)


if __name__ == '__main__':
  unittest.main()
