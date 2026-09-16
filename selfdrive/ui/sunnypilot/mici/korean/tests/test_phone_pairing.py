import importlib
import sys
import types
import unittest
from unittest.mock import patch
from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_pairing import pairing_payload, qr_tiles
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_runtime import PhoneRuntime
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_home import HomeSM
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_management import Store


def native_module():
  class Widget:
    def __init__(self):
      self.dismissed = False
    def set_rect(self, rect):
      self.rect = rect
    def dismiss(self):
      self.dismissed = True
  def rect(x, y, width, height):
    return types.SimpleNamespace(x=x, y=y, width=width, height=height)
  modules = {'pyray': types.SimpleNamespace(Rectangle=rect),
             'openpilot.system.ui.widgets': types.SimpleNamespace(Widget=Widget),
             'openpilot.system.ui.lib.application': types.SimpleNamespace(gui_app=types.SimpleNamespace(push_widget=lambda page: None))}
  with patch.dict(sys.modules, modules):
    # All rendering still uses the real phone page and its real display list.
    return importlib.import_module('openpilot.selfdrive.ui.sunnypilot.mici.korean.native_phone')


class PairingUiTest(unittest.TestCase):
  def setUp(self):
    self.now = 100.
    self.store = Store()
    self.runtime = PhoneRuntime(self.store, clock=lambda: self.now)
    self.runtime.update(HomeSM(self.now), 10, True)
    self.runtime.service.device_set_home(True)
    self.runtime.transport = types.SimpleNamespace(url='https://10.209.29.93:7443', fingerprint='ab'*32, close=lambda: None)
    self.native = native_module()
    self.page = self.native.KoreanPhonePage(self.runtime)
    self.addCleanup(self.runtime.close)

  def render(self):
    with patch.object(drawing, 'render_native'):
      self.page._render(None)
    for key, (x,y,w,h) in self.page.actions:
      self.assertGreaterEqual(h,48)
      self.assertGreaterEqual(w,112)
      self.assertTrue(0<=x<x+w<=536 and 0<=y<y+h<=240)
    for op,a in drawing.commands():
      if op == 'alert_text': self.assertGreaterEqual(a[3],24)

  def tap(self, key):
    rect = next(r for k,r in self.page.actions if k==key)
    self.page._handle_mouse_release(types.SimpleNamespace(x=rect[0]+rect[2]/2,y=rect[1]+rect[3]/2))

  def test_qr_contains_complete_pin_and_pair_still_requires_local_consent(self):
    self.render(); self.tap('open'); self.render()
    data = self.page.qr_payload.split(':')
    self.assertEqual(data[:3], ['KORANI1','10.209.29.93','7443'])
    self.assertEqual(data[3], 'AB'*32)
    ticket=self.runtime.service.pair(data[4], '내 안드로이드')
    self.assertEqual(self.runtime.service.status(ticket)[0]['state'],'pending')
    self.render(); self.assertFalse(self.page.show_qr)
    self.tap('approve')
    self.assertEqual(self.runtime.service.status(ticket)[0]['state'],'connected')
    self.assertEqual(self.store.writes,[])

  def test_stale_qr_disappears_after_device_state_loss(self):
    self.render();self.tap('open');self.render()
    code=self.page.qr_payload.split(':')[-1]
    self.now+=2
    self.render()
    self.assertIsNone(self.page.qr_payload)
    with self.assertRaises(PhoneError): self.runtime.service.pair(code,'phone')

  def test_old_frame_cannot_approve_a_replaced_request(self):
    self.render();self.tap('open');self.render()
    service=self.runtime.service
    service.pair(self.page.qr_payload.split(':')[-1],'first')
    self.render()
    service.device_open()
    ticket=service.pair(service.device_view()['window']['code'],'second')
    self.tap('approve')
    self.assertEqual(service.status(ticket)[0]['state'],'pending')

  def test_unseen_pending_request_cannot_be_erased_by_refresh(self):
    self.render();self.tap('open');self.render()
    service=self.runtime.service
    ticket=service.pair(self.page.qr_payload.split(':')[-1],'first')
    self.tap('open')
    self.assertEqual(service.status(ticket)[0]['state'],'pending')

  def test_home_page_controls_fit_and_return_after_explicit_choice(self):
    self.page=self.native.HomeReceivePage(self.runtime)
    self.render();self.tap('home')
    self.assertTrue(self.page.dismissed)
    self.assertTrue(self.runtime.service.mode_view()['home_active'])

  def test_network_retry_does_not_replace_live_transport_or_pair(self):
    current=self.runtime.transport
    self.assertFalse(self.runtime.retry_local_transport())
    self.assertIs(self.runtime.transport,current)
    self.runtime.transport=None
    with patch.dict('os.environ', {'KOREAN_PHONE_LOCAL':'0'}):
      self.assertFalse(self.runtime.retry_local_transport())
    with patch.dict('os.environ', {'KOREAN_PHONE_LOCAL':'1'}), patch('openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_transport.local_phone_transport',side_effect=OSError):
      self.assertFalse(self.runtime.retry_local_transport())
    with patch.dict('os.environ', {'KOREAN_PHONE_LOCAL':'1'}), patch('openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_transport.local_phone_transport',return_value=current):
      self.assertTrue(self.runtime.retry_local_transport())
    self.assertEqual(self.runtime.service.device_view()['sessions'],[])
    self.assertEqual(self.store.writes,[])

  def test_qr_geometry_and_bad_destinations(self):
    good=pairing_payload('https://192.168.255.254:65535','fe'*32,'001234')
    self.assertIn(':001234',good)
    tiles=qr_tiles(good)
    self.assertTrue(tiles)
    self.assertTrue(all(304<=x<x+w<=520 and 12<=y<y+h<=228 and h>=3 for x,y,w,h in tiles))
    for url in ('http://10.0.0.1','https://8.8.8.8','https://127.0.0.1','https://10.0.0.1/path','https://user@10.0.0.1','https://10.0.0.1?x=1'):
      with self.subTest(url=url),self.assertRaises(ValueError):pairing_payload(url,'ab'*32,'123456')
