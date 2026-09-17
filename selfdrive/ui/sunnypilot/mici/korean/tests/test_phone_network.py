import ast
import errno
import os
from pathlib import Path
import tempfile
import time
import types
import unittest
from enum import IntEnum
from unittest.mock import patch

from openpilot.common import koranipilot
from openpilot.selfdrive.ui.sunnypilot.mici.korean import phone_transport as transport
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_runtime import PhoneRuntime
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_management import Store
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_home import HomeSM

ROOT = Path(__file__).resolve().parents[6]


class Status(IntEnum):
  DISCONNECTED = 0
  CONNECTING = 1
  CONNECTED = 2


def network_panel(manager):
  # Execute the production read-only property with a synthetic NetworkManager.
  path = ROOT / 'selfdrive/ui/mici/layouts/settings/network/network_layout.py'
  cls = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'NetworkLayoutMici')
  prop = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'connected_wifi_ipv4')
  scope = {'ConnectStatus': Status}
  exec(compile(ast.Module(body=[prop], type_ignores=[]), str(path), 'exec'), scope)
  panel_type = type('NetworkPanel', (), {'connected_wifi_ipv4': scope['connected_wifi_ipv4']})
  panel = panel_type()
  panel._wifi_manager = manager
  return panel


class NetworkAddressTest(unittest.TestCase):
  def test_network_card_and_pairing_share_only_connected_address(self):
    manager = types.SimpleNamespace(wifi_state=types.SimpleNamespace(status=Status.CONNECTED), ipv4_address='10.209.29.93')
    panel = network_panel(manager)
    self.assertEqual(panel.connected_wifi_ipv4, manager.ipv4_address)
    for status in (Status.CONNECTING, Status.DISCONNECTED):
      manager.wifi_state.status = status
      self.assertIsNone(panel.connected_wifi_ipv4)
    manager.wifi_state.status = Status.CONNECTED
    manager.ipv4_address = ''
    self.assertIsNone(panel.connected_wifi_ipv4)

  def test_named_interface_failure_does_not_block_network_manager_address(self):
    server = object()
    with tempfile.TemporaryDirectory() as tmp, patch.object(transport, 'local_ipv4', side_effect=OSError('no wlan0/eth0')) as legacy:
      with self.assertRaises(transport.PhoneStartupError) as old:
        transport.local_phone_transport(object(), identity_root=tmp)
      self.assertEqual(old.exception.stage, 'address')
      legacy.reset_mock()
      with patch.object(transport, 'PhoneTransport', return_value=server) as listener:
        actual = transport.local_phone_transport(object(), identity_root=tmp, address_provider=lambda: '10.209.29.93')
      legacy.assert_not_called()
      self.assertIs(actual, server)
      self.assertEqual(listener.call_args.kwargs['host'], '10.209.29.93')
      self.assertEqual(listener.call_args.kwargs['authority'], '10.209.29.93:7443')
      from cryptography import x509
      cert = x509.load_pem_x509_certificate(Path(listener.call_args.kwargs['certfile']).read_bytes())
      self.assertEqual(str(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value[0].value), '10.209.29.93')

  def test_unready_or_non_lan_provider_never_falls_back_or_opens_listener(self):
    for value in (None, '', 'not an ip', '127.0.0.1', '0.0.0.0', '169.254.1.2', '100.64.1.2', '8.8.8.8', '::1', 123):
      with self.subTest(value=value), patch.object(transport, 'local_ipv4') as legacy, patch.object(transport, 'ensure_tls_identity') as identity, patch.object(transport, 'PhoneTransport') as listener:
        with self.assertRaises(transport.PhoneStartupError) as error:
          transport.local_phone_transport(object(), address_provider=lambda: value)
        self.assertEqual((error.exception.stage, error.exception.code), ('address', 'EADDRNOTAVAIL'))
        legacy.assert_not_called(); identity.assert_not_called(); listener.assert_not_called()

  def test_new_address_is_read_at_retry_without_pairing_or_settings_writes(self):
    manager = types.SimpleNamespace(wifi_state=types.SimpleNamespace(status=Status.CONNECTING), ipv4_address='10.0.0.2')
    panel = network_panel(manager)
    store = Store()
    runtime = PhoneRuntime(store, address_provider=lambda: panel.connected_wifi_ipv4)
    self.addCleanup(runtime.close)
    server = types.SimpleNamespace(close=lambda: None)
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, KOREAN_PHONE_LOCAL='1'), patch.object(koranipilot, 'local_data_root', return_value=tmp), patch.object(transport, 'local_ipv4', side_effect=AssertionError('must use network card')):
      self.assertFalse(runtime.retry_local_transport())
      self.assertIn('EADDRNOTAVAIL', runtime.network_error)
      manager.wifi_state.status = Status.CONNECTED
      manager.ipv4_address = '192.168.43.21'
      with patch.object(transport, 'PhoneTransport', return_value=server) as listener:
        self.assertTrue(runtime.retry_local_transport())
        self.assertEqual(listener.call_args.kwargs['host'], '192.168.43.21')
        self.assertFalse(runtime.retry_local_transport())
        self.assertEqual(listener.call_count, 1)
    self.assertEqual(runtime.network_error, '')
    self.assertEqual(runtime.service.device_view()['sessions'], [])
    self.assertIsNone(runtime.service.device_view()['window'])
    self.assertEqual(store.writes, [])

  def test_native_constructor_passes_live_network_panel_provider(self):
    manager = types.SimpleNamespace(wifi_state=types.SimpleNamespace(status=Status.CONNECTING), ipv4_address='')
    panel = network_panel(manager)
    class Base:
      def __init__(self):
        self._network_panel = panel
        items = []
        self._scroller = types.SimpleNamespace(_items=items, add_widget=items.append)
    store = Store()
    ui = types.SimpleNamespace(params=store, sm=HomeSM(time.monotonic()), started_frame=10, is_release=True, is_sp_release=True,
                               add_update_callback=lambda _: None, remove_update_callback=lambda _: None)
    gui = types.SimpleNamespace(add_nav_stack_tick=lambda _: None, remove_nav_stack_tick=lambda _: None)
    path = ROOT / 'selfdrive/ui/sunnypilot/mici/korean/native_settings.py'
    cls = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'PhoneSettingsRoot')
    scope = {'DrivingSettingsRoot': Base, 'os': os, 'ui_state': ui, 'gui_app': gui, 'atexit': types.SimpleNamespace(register=lambda _: None)}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), 'exec'), scope)
    modules = {'openpilot.selfdrive.ui.sunnypilot.mici.korean.native_phone': types.SimpleNamespace(KoreanPhoneButton=lambda _: object())}
    with patch.dict(os.environ, KOREAN_PHONE_LOCAL='1', KOREAN_PHONE_CERT='', KOREAN_PHONE_SETTINGS_WRITE='0', KOREAN_ROAD_INPUT='0'), patch.dict('sys.modules', modules):
      root = scope['PhoneSettingsRoot']()
      self.addCleanup(root.close_phone)
      self.assertIsNone(root.phone_runtime.transport)
      self.assertIn('EADDRNOTAVAIL', root.phone_runtime.network_error)
      manager.wifi_state.status = Status.CONNECTED
      manager.ipv4_address = '10.209.29.93'
      self.assertEqual(root.phone_runtime.address_provider(), '10.209.29.93')
      self.assertEqual(store.writes, [])

  def test_initial_address_read_does_not_require_opening_network_page(self):
    # Exercise the real initializer with synchronous thread doubles and no scan.
    path = ROOT / 'system/ui/lib/wifi_manager.py'
    cls = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'WifiManager')
    initialize = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_initialize')
    class Thread:
      def __init__(self, target, **kwargs): self.target = target
      def start(self): self.target()
    from unittest.mock import Mock
    logs = Mock()
    scope = {'threading': types.SimpleNamespace(Thread=Thread), 'Params': None, 'cloudlog': logs}
    exec(compile(ast.Module(body=[initialize], type_ignores=[]), str(path), 'exec'), scope)
    for fail in (False, True):
      with self.subTest(read_failure=fail):
        manager = types.SimpleNamespace(_active=False, _ipv4_address='', _wait_for_wifi_device=Mock(),
          _scan_thread=Mock(), _state_thread=Mock(), _init_connections=Mock(),
          _init_wifi_state=Mock(), _get_tethering_password=Mock(return_value='synthetic'))
        def refresh():
          if fail: raise OSError('simulated network manager startup delay')
          manager._ipv4_address = '10.209.29.93'
        manager._update_active_connection_info = Mock(side_effect=refresh)
        scope['_initialize'](manager)
        manager._update_active_connection_info.assert_called_once_with()
        self.assertFalse(manager._active)
        self.assertEqual(manager._tethering_password, 'synthetic')
        if not fail: self.assertEqual(manager._ipv4_address, '10.209.29.93')
