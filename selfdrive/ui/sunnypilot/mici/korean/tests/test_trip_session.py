import unittest  # noqa: TID251 - shares the phone regression fixtures
import http.client
import json
import ssl
import tempfile

from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_runtime import PhoneRuntime
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError, SETTINGS_TTL
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_transport import PhoneTransport, ensure_tls_identity
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_management import Store, SM
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_home import HomeSM
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_kakao import frame


class TripSessionTest(unittest.TestCase):
  def setUp(self):
    self.now = 100.
    self.store = Store()
    self.runtime = PhoneRuntime(self.store, clock=lambda: self.now)
    self.addCleanup(self.runtime.close)
    self.service = self.runtime.service
    self.sequence = 0

  def connect(self, home=False):
    self.home = home
    self.refresh()
    if home:
      self.service.device_set_home(True)
    ticket = self.service.pair(self.service.device_open()['window']['code'], 'Trip phone')
    self.service.device_decide(self.service.pending['id'], True)
    state, self.token = self.service.status(ticket)
    self.csrf, self.session_id = state['csrf'], state['session_id']

  def refresh(self):
    self.runtime.update(HomeSM(self.now) if self.home else SM(self.now), 10, True)

  def advance(self, seconds):
    # Keep hardware telemetry continuously fresh, not just after a clock jump.
    for _ in range(int(seconds)):
      self.now += 1
      self.refresh()
    if seconds % 1:
      self.now += seconds % 1
      self.refresh()

  def observe(self):
    challenge = self.service.kakao.challenge(self.token)['challenge']
    self.sequence += 1
    return self.service.kakao.accept(self.token, self.csrf, frame(challenge, self.sequence))

  def test_eight_hour_trip_receives_without_renewing_write_permission(self):
    for home in (True, False):
      with self.subTest(home=home):
        self.connect(home)
        started = self.now
        for elapsed in (1799, 1800, 1801, 7200, 28800):
          self.advance(started + elapsed - self.now)
          self.assertEqual(self.observe()['received'], True)
          state = self.service.status(self.token)[0]
          self.assertIsNone(state['remaining'])
          self.assertEqual(state['state'], 'connected')
        self.assertEqual(state['settings_remaining'], 0)
        self.service.disconnect(self.token)
        if home:
          self.service.device_set_home(False)
    self.assertEqual(self.store.writes, [])

  def test_settings_expire_with_connection_and_road_authorization_preserved(self):
    self.connect()
    self.advance(SETTINGS_TTL)
    for operation in (lambda: self.service.change(self.token, self.csrf, {}),
                      lambda: self.service.change(self.token, self.csrf, {}, catalog=True),
                      lambda: self.service.model_change(self.token, self.csrf, {})):
      with self.assertRaises(PhoneError) as error:
        operation()
      self.assertEqual(error.exception.code, 'settings_approval_expired')
    self.assertEqual(self.observe()['received'], True)
    self.service.authorize_write(self.token, self.csrf)  # vehicle road input, not settings
    self.assertFalse(any(r['editable'] for r in self.service.view(self.token)['rows']))
    self.assertFalse(self.service.overview(self.token)['models']['editable'])
    self.assertEqual(self.store.writes, [])

  def test_only_native_parked_approval_renews_settings(self):
    self.connect()
    self.advance(SETTINGS_TTL)
    self.service.device_approve_settings(self.session_id)
    self.assertEqual(self.service.status(self.token)[0]['settings_remaining'], SETTINGS_TTL)
    self.service.authorize_write(self.token, self.csrf, settings=True)
    self.now += 2  # stale vehicle data must not grant another approval
    with self.assertRaises(PhoneError):
      self.service.device_approve_settings(self.session_id)

  def test_home_rejects_settings_renewal_and_road_input_after_long_trip(self):
    self.connect(True)
    self.advance(28800)
    for operation in (lambda: self.service.device_approve_settings(self.session_id),
                      lambda: self.service.authorize_write(self.token, self.csrf)):
      with self.assertRaises(PhoneError) as error:
        operation()
      self.assertEqual(error.exception.code, 'receive_only')
    self.assertEqual(self.store.writes, [])

  def test_payload_still_expires_and_bad_csrf_cannot_send(self):
    self.connect(True)
    self.observe()
    self.advance(3.1)
    self.assertFalse(self.service.kakao.view()['received'])
    self.assertEqual(self.service.status(self.token)[0]['state'], 'connected')
    with self.assertRaises(PhoneError) as error:
      self.service.authorize_write(self.token, 'invalid', observation=True)
    self.assertEqual(error.exception.code, 'csrf')

  def test_explicit_disconnect_revoke_and_home_state_loss_still_revoke(self):
    for end in ('disconnect', 'revoke', 'state_loss', 'mode_change', 'close'):
      with self.subTest(end=end):
        if self.service.closed:
          break
        self.connect(True)
        self.observe()
        if end == 'disconnect':
          self.service.disconnect(self.token)
        elif end == 'revoke':
          self.service.device_revoke(self.session_id)
        elif end == 'mode_change':
          self.service.device_set_home(False)
        elif end == 'close':
          self.service.close()
        else:
          self.now += 2
        with self.assertRaises(PhoneError):
          self.service.session(self.token)
        self.assertFalse(self.service.kakao.view()['received'])

  def test_https_cookie_has_no_timer_and_old_approval_cannot_write(self):
    self.home = False
    self.refresh()
    ticket = self.service.pair(self.service.device_open()['window']['code'], 'TLS trip')
    self.service.device_decide(self.service.pending['id'], True)
    with tempfile.TemporaryDirectory() as root:
      cert, key = ensure_tls_identity(root, '127.0.0.1')
      transport = PhoneTransport(self.service, host='127.0.0.1', port=0, authority='127.0.0.1', certfile=cert, keyfile=key)
      self.addCleanup(transport.close)
      cookie = '__Secure-korean_phone=' + ticket
      def call(path, body=None, csrf=''):
        connection = http.client.HTTPSConnection('127.0.0.1', transport.server.server_port, context=ssl._create_unverified_context())
        headers = {'Host': '127.0.0.1', 'Origin': 'https://127.0.0.1', 'Cookie': cookie,
                   'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}
        connection.request('POST' if body is not None else 'GET', '/api/phone/' + path,
                           None if body is None else json.dumps(body), headers)
        response = connection.getresponse()
        value = response.status, json.loads(response.read()), response.getheader('Set-Cookie')
        connection.close()
        return value
      status, state, header = call('session')
      self.assertEqual(status, 200)
      self.assertNotIn('Max-Age', header)
      cookie = header.split(';', 1)[0]
      self.advance(28800)
      self.assertEqual(call('session')[0], 200)
      status, value, _ = call('changes', {}, state['csrf'])
      self.assertEqual((status, value['code']), (403, 'settings_approval_expired'))
      challenge = call('kakao')[1]['challenge']
      self.assertEqual(call('kakao', frame(challenge), state['csrf'])[0], 200)
      status, _, header = call('logout', {}, state['csrf'])
      self.assertEqual(status, 200)
      self.assertIn('Max-Age=0', header)
      self.assertEqual(call('session')[0], 401)
