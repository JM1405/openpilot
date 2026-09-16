import ast
import errno
import os
from pathlib import Path
import ssl
import tempfile
import types
import unittest
from unittest.mock import patch

from openpilot.common import koranipilot
from openpilot.selfdrive.ui.sunnypilot.mici.korean import phone_transport as transport
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_management import Store

ROOT = Path(__file__).resolve().parents[6]


class StartupTest(unittest.TestCase):
  def test_identity_uses_app_data_not_readonly_persist(self):
    with patch.dict('sys.modules', {'openpilot.system.hardware': types.SimpleNamespace(PC=False),
                                   'openpilot.system.hardware.hw': types.SimpleNamespace(Paths=object)}):
      self.assertEqual(koranipilot.local_data_root(), '/data/koranipilot')
    with tempfile.TemporaryDirectory() as tmp:
      with patch.object(koranipilot, 'local_data_root', return_value=tmp):
        server = transport.local_phone_transport(object(), address='127.0.0.1', port=0)
      try:
        cert = Path(tmp) / 'phone_tls/phone-127_0_0_1.crt'
        key = cert.with_suffix('.key')
        self.assertTrue(cert.is_file())
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        first = cert.read_bytes()
        self.assertEqual(transport.ensure_tls_identity(cert.parent, '127.0.0.1')[0], str(cert))
        self.assertEqual(cert.read_bytes(), first)
      finally:
        server.close()

  def test_failures_are_classified_without_echoing_sensitive_exception(self):
    cases = [('local_ipv4', OSError(errno.ENODEV, 'secret'), 'address', 'ENODEV'),
             ('ensure_tls_identity', OSError(errno.EROFS, 'secret private key'), 'identity', 'EROFS'),
             ('ensure_tls_identity', ModuleNotFoundError('secret path'), 'identity', 'ModuleNotFoundError'),
             ('PhoneTransport', OSError(errno.EADDRINUSE, 'secret'), 'server', 'EADDRINUSE'),
             ('PhoneTransport', ssl.SSLError('secret'), 'server', 'SSLError')]
    for target, exc, stage, code in cases:
      with self.subTest(target=target, code=code), tempfile.TemporaryDirectory() as tmp:
        with patch.object(transport, target, side_effect=exc):
          with self.assertRaises(transport.PhoneStartupError) as caught:
            transport.local_phone_transport(object(), address=None if target == 'local_ipv4' else '127.0.0.1', identity_root=tmp, port=0)
        self.assertEqual((caught.exception.stage, caught.exception.code), (stage, code))
        self.assertNotIn('secret', caught.exception.display)

  def test_retry_shows_storage_failure_then_recovers_without_approval(self):
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_pairing import PairingUiTest
    fixture = PairingUiTest(); fixture.setUp()
    try:
      current = fixture.runtime.transport
      fixture.runtime.transport = None
      failure = transport.PhoneStartupError('identity', OSError(errno.EROFS, 'private'))
      with patch.dict(os.environ, KOREAN_PHONE_LOCAL='1'), patch.object(transport, 'local_phone_transport', side_effect=failure):
        fixture.render(); fixture.tap('retry'); fixture.render()
      from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing
      texts = [a[0] for op,a in drawing.commands() if op == 'alert_text']
      self.assertIn('인증서 저장을 확인해줘', texts)
      self.assertIn('EROFS', texts)
      with patch.dict(os.environ, KOREAN_PHONE_LOCAL='1'), patch.object(transport, 'local_phone_transport', return_value=current):
        fixture.tap('retry'); fixture.render()
      self.assertEqual(fixture.runtime.network_error, '')
      self.assertIsNone(fixture.runtime.service.device_view()['window'])
      self.assertEqual(fixture.store.writes, [])
    finally:
      fixture.doCleanups()


class BrandTest(unittest.TestCase):
  def test_upstream_acceptance_cannot_satisfy_fork_or_reverse(self):
    params = Store()
    params.data.update(HasAcceptedTerms='2', HasAcceptedTermsSP='1.0')
    with patch.dict(os.environ, KOREAN_PHONE_LOCAL='1'):
      self.assertEqual(koranipilot.accepted_notices(params, '2', '1.0'), (False, False))
      self.assertEqual(koranipilot.product_name(), 'Koranipilot')
      for key, version in zip(('HasAcceptedTerms','HasAcceptedTermsSP'), koranipilot.notice_versions('2', '1.0')):
        params.put(key, version)
      self.assertEqual(koranipilot.accepted_notices(params, '2', '1.0'), (True, True))
    with patch.dict(os.environ, KOREAN_PHONE_LOCAL='0'):
      self.assertEqual(koranipilot.accepted_notices(params, '2', '1.0'), (False, False))
      self.assertEqual(koranipilot.product_name(), 'sunnypilot')

  def test_onboarding_visible_cards_and_explicit_acceptance(self):
    # Execute the actual production class definitions with non-rendering widgets.
    # This checks constructors/callbacks, not the real C4 renderer or fonts.
    class Widget:
      def __init__(self, *args, **kwargs):
        self.text = args[0] if args else ''
        self.value = args[1] if len(args)>1 else ''
        self._scroller = self; self.items=[]; self.enabled=True
      def add_widgets(self, items): self.items.extend(items)
      def add_widget(self, item): self.items.append(item)
      def set_rect(self, *args): pass
      def set_enabled(self, *args): pass
      def set_text(self, text): self.text=text
      def set_value(self, text): self.value=text
      def set_click_callback(self, callback): self.click=callback
    class Circle:
      def __init__(self,title,icon,callback,**kwargs): self.title=title; self.click=callback
    params=Store()
    params.data.update(HasAcceptedTerms='2',HasAcceptedTermsSP='1.0',CompletedTrainingVersion='training')
    gui=types.SimpleNamespace(texture=lambda *a,**k:None,width=536,height=240,push_widget=lambda w:None)
    ns=dict(Widget=Widget,Scroller=Widget,NavScroller=Widget,NavRawScrollPanel=Widget,
            GreyBigButton=Widget,BigButton=Widget,BigConfirmationCircleButton=Circle,Callable=object,
            gui_app=gui,ui_state=types.SimpleNamespace(params=params),rl=types.SimpleNamespace(Rectangle=lambda *a:a),
            terms_version='2',terms_version_sp='1.0',training_version='training',
            sunnylink_consent_version='cloud',sunnylink_consent_declined='no',
            koranipilot_enabled=koranipilot.enabled,brand_text=koranipilot.brand_text,
            accepted_notices=koranipilot.accepted_notices,notice_versions=koranipilot.notice_versions,
            TrainingGuide=lambda **kwargs:Widget(), SunnylinkConsentPage=lambda **kwargs:self.fail('cloud consent constructed'))
    # Callable annotations need a subscriptable typing symbol.
    from collections.abc import Callable
    ns['Callable']=Callable
    tree=ast.parse((ROOT/'selfdrive/ui/mici/layouts/onboarding.py').read_text())
    names={'TermsPage','OnboardingWindow','OpenSourcePage','LicenseTextPage'}
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in names],type_ignores=[]),'<production onboarding>','exec'),ns)
    with patch.dict(os.environ,KOREAN_PHONE_LOCAL='1'):
      closed=[]
      window=ns['OnboardingWindow'](lambda:closed.append(True))
      self.assertFalse(window.completed)
      self.assertEqual(params.writes,[])
      labels=' '.join(str(getattr(i,'text',''))+' '+str(getattr(i,'value','')) for i in window._terms.items)
      self.assertIn('Koranipilot',labels)
      self.assertNotIn('sunnypilot',labels)
      self.assertNotIn('sunnylink',labels)
      self.assertIsNone(window._sunnylink_consent)
      self.assertEqual(window._terms._accept_button.title,'I understand')
      window._terms._accept_button.click()
      self.assertTrue(window.completed)
      self.assertEqual(closed,[True])
      self.assertNotIn('SunnylinkEnabled',[item[0] for item in params.writes])
      self.assertEqual(params.data['HasAcceptedTermsSP'],koranipilot.NOTICE_VERSION)

  def test_home_cloud_service_guards_preserve_saved_consent(self):
    # Load actual service gate without importing hardware-specific native Params.
    ns={'koranipilot_enabled':koranipilot.enabled,'UNREGISTERED_SUNNYLINK_DONGLE_ID':'unregistered'}
    tree=ast.parse((ROOT/'sunnypilot/sunnylink/utils.py').read_text())
    funcs={'get_sunnylink_status','sunnylink_ready','sunnylink_need_register','use_sunnylink_uploader'}
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in funcs],type_ignores=[]),'<production cloud gates>','exec'),ns)
    params=Store();params.data.update(SunnylinkEnabled=True,SunnylinkDongleId='registered',SunnylinkTempFault=False,EnableSunnylinkUploader=True)
    params.get_bool=lambda key:bool(params.get(key))
    with patch.dict(os.environ,KOREAN_PHONE_LOCAL='1'):
      self.assertFalse(ns['sunnylink_ready'](params))
      self.assertFalse(ns['sunnylink_need_register'](params))
      self.assertFalse(ns['use_sunnylink_uploader'](params))
    with patch.dict(os.environ,KOREAN_PHONE_LOCAL='0'):
      self.assertTrue(ns['sunnylink_ready'](params))
    self.assertTrue(params.data['SunnylinkEnabled'])
    self.assertEqual(params.writes,[])
