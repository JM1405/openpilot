import http.client
import json
import ssl
import tempfile
import unittest  # noqa: TID251 - shares the existing phone regression fixtures
from unittest.mock import patch  # noqa: TID251

from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_home import HOME_MODE
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_runtime import PhoneRuntime
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError, SESSION_TTL, CODE_TTL
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_transport import PhoneTransport, ensure_tls_identity
from openpilot.selfdrive.ui.sunnypilot.mici.korean.settings import SettingsError
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_management import Store, SM, Message
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_kakao import frame


class HomeSM(SM):
  """Hardware-only fixture. No carState, CAN, carParams, or controls samples."""
  def __init__(self, now):
    super().__init__(now)
    self.services.add('pandaStates')
    self.seen = dict.fromkeys(self.services, False)
    self.valid = dict.fromkeys(self.services, False)
    self.recv_frame = dict.fromkeys(self.services, -1)
    self.recv_time = dict.fromkeys(self.services, 0.)
    self.data = {}
    self.feed('deviceState', {'deviceType': 'mici', 'started': False}, now)
    self.feed('pandaStates', [{'pandaType': 'cuatro', 'ignitionLine': False, 'ignitionCan': False,
                             'safetyModel': 'noOutput', 'controlsAllowed': False,
                             'controlsAllowedLateral': False, 'controlsAllowedLongitudinal': False}], now)

  def __getitem__(self, key):
    return [Message(item) for item in self.data[key]] if key == 'pandaStates' else super().__getitem__(key)


class PhoneHomeTest(unittest.TestCase):
  def setUp(self):
    self.now, self.store = 100., Store()
    # Deliberately permissive deployment flags: home scope must still win.
    self.runtime = PhoneRuntime(self.store, clock=lambda: self.now, allow_model_change=True, allow_settings_change=True)
    self.addCleanup(self.runtime.close)
    self.service = self.runtime.service
    self.sm = HomeSM(self.now)
    self.runtime.update(self.sm, 10, True)

  def tearDown(self):
    self.assertEqual(self.store.writes, [])

  def connect(self):
    self.service.device_set_home(True)
    ticket = self.service.pair(self.service.device_open()['window']['code'], 'Home Android')
    self.assertEqual(self.service.status(ticket)[0]['state'], 'pending')
    with self.assertRaises(PhoneError):
      self.service.kakao.challenge(ticket)
    self.service.device_decide(self.service.pending['id'], True)
    state, token = self.service.status(ticket)
    return token, state['csrf']

  def test_mode_off_keeps_existing_vehicle_gate(self):
    with self.assertRaises(PhoneError) as error:
      self.service.device_open()
    self.assertEqual(error.exception.status, 422)
    self.assertFalse(self.runtime.controller.view()['parked'])

  def test_missing_device_data_is_not_permission(self):
    self.runtime.inputs.clear()
    with self.assertRaises(PhoneError):
      self.service.device_set_home(True)
    self.assertEqual(self.service.mode, 'vehicle')

  def test_native_approval_and_observation_without_car_signals(self):
    token, csrf = self.connect()
    state = self.service.overview(token)
    self.assertFalse(state['settings']['parked'])
    self.assertEqual(state['connection']['mode'], HOME_MODE)
    self.assertFalse(state['models']['editable'])
    payload = frame(self.service.kakao.challenge(token)['challenge'])
    result = self.service.kakao.accept(token, csrf, payload)
    self.assertTrue(result['received'])
    self.assertFalse(result['control_enabled'])
    self.assertEqual(result['events'][0]['distance_m'], None)
    self.assertFalse(result['events'][0]['control_eligible'])

  def test_all_mutators_block_even_with_valid_vehicle_state_and_write_flags(self):
    token, csrf = self.connect()
    parked = SM(self.now)
    for name in parked.services - {'deviceState'}:
      self.sm.feed(name, parked.data[name], self.now)
    self.runtime.update(self.sm, 10, False)
    self.assertTrue(self.runtime.controller.view()['parked'])  # real fixture, no spoofing in home gate
    calls = [lambda: self.service.change(token, csrf, {}), lambda: self.service.model_change(token, csrf, {}),
             lambda: self.service.navigation.accept(token, csrf, {}),
             lambda: self.service.road_input.accept(token, csrf, 'fix', {})]
    for call in calls:
      with self.assertRaises(PhoneError) as error:
        call()
      self.assertEqual(error.exception.code, 'receive_only')
    with self.assertRaises(SettingsError):
      self.runtime.controller.save('mads', False, self.runtime.controller.view()['revision'], acknowledged=True)
    models = self.service.management.models()
    with self.assertRaises(SettingsError):
      self.service.management.request_model('model/test', models['revision'], acknowledged=True)
    self.assertTrue(all(not row['editable'] for row in self.service.overview(token)['settings']['rows']))
    with self.assertRaises(RuntimeError):
      self.runtime.attach_road_publisher()

  def test_home_cannot_start_with_road_publisher(self):
    with patch.object(self.runtime, 'road_publisher', object()):
      with self.assertRaises(PhoneError):
        self.service.device_set_home(True)

  def test_rejects_missing_invalid_stale_future_and_previous_epoch_messages(self):
    for name in ('deviceState', 'pandaStates'):
      for field, value in (('seen', False), ('valid', False), ('recv_frame', 9),
                           ('recv_time', self.now-1.5), ('recv_time', self.now+.001), ('recv_time', float('nan'))):
        with self.subTest(name=name, field=field, value=value):
          sm = HomeSM(self.now)
          getattr(sm, field)[name] = value
          self.runtime.update(sm, 10, True)
          with self.assertRaises(PhoneError):
            self.service.device_set_home(True)

  def test_rejects_started_ignition_unknown_panda_and_output_permission(self):
    changes = [('deviceState', 'started', True), ('deviceState', 'started', None),
               ('pandaStates', 'pandaType', 'unknown'), ('pandaStates', 'ignitionCan', True),
               ('pandaStates', 'ignitionLine', True), ('pandaStates', 'ignitionLine', 0),
               ('pandaStates', 'safetyModel', 'hyundaiCanfd'), ('pandaStates', 'controlsAllowed', True),
               ('pandaStates', 'controlsAllowedLateral', True), ('pandaStates', 'controlsAllowedLongitudinal', True)]
    for name, key, value in changes:
      with self.subTest(key=key):
        sm = HomeSM(self.now)
        target = sm.data[name][0] if name == 'pandaStates' else sm.data[name]
        target[key] = value
        self.runtime.update(sm, 10, True)
        with self.assertRaises(PhoneError):
          self.service.device_set_home(True)
    for pandas in ([], [{'pandaType': 'cuatro'}], [HomeSM(self.now).data['pandaStates'][0], {'pandaType': 'unknown'}]):
      sm = HomeSM(self.now)
      sm.feed('pandaStates', pandas, self.now)
      self.runtime.update(sm, 10, True)
      with self.assertRaises(PhoneError):
        self.service.device_set_home(True)

  def test_conflicting_vehicle_or_controls_data_stops_home(self):
    conflicts = [('carState', {'canValid': True, 'vEgo': 1., 'standstill': False, 'gearShifter': 'drive'}),
                 ('carControl', {'latActive': True}), ('selfdriveState', {'enabled': True}),
                 ('selfdriveStateSP', {'mads': {'active': True}})]
    for name, data in conflicts:
      self.runtime.update(HomeSM(self.now), 10, True)
      token, _ = self.connect()
      sm = HomeSM(self.now)
      sm.feed(name, data, self.now)
      self.runtime.update(sm, 10, True)
      with self.assertRaises(PhoneError):
        self.service.session(token)
      self.assertFalse(self.service.home_active)

  def test_state_loss_revokes_and_does_not_resume_on_fresh_data(self):
    token, csrf = self.connect()
    self.service.kakao.accept(token, csrf, frame(self.service.kakao.challenge(token)['challenge']))
    self.now += 1.5
    self.assertFalse(self.service.kakao.view()['received'])
    self.runtime.update(HomeSM(self.now), 10, True)
    self.assertFalse(self.service.home_active)
    self.assertEqual(self.service.mode, HOME_MODE)  # never silently fall back to privileged vehicle mode
    with self.assertRaises(PhoneError):
      self.service.device_open()
    with self.assertRaises(PhoneError):
      self.service.session(token)
    replacement, _ = self.connect()
    self.assertNotEqual(token, replacement)

  def test_update_gap_revokes_even_when_new_messages_are_fresh(self):
    token, _ = self.connect()
    self.now += 1.5
    self.runtime.update(HomeSM(self.now), 10, True)
    self.assertFalse(self.service.home_active)
    with self.assertRaises(PhoneError):
      self.service.session(token)

  def test_state_loss_during_each_approval_stage_invalidates_ticket(self):
    for stage in ('code', 'pending', 'approved'):
      self.runtime.update(HomeSM(self.now), 10, True)
      self.service.device_set_home(True)
      code = self.service.device_open()['window']['code']
      ticket = self.service.pair(code, 'Android') if stage != 'code' else None
      pending_id = self.service.pending['id'] if ticket else None
      if stage == 'approved':
        self.service.device_decide(pending_id, True)
      self.now += 1.5
      with self.assertRaises(PhoneError):
        if stage == 'code':
          self.service.pair(code, 'Android')
        elif stage == 'pending':
          self.service.device_decide(pending_id, True)
        else:
          self.service.status(ticket)
      self.assertFalse(self.service.home_active)
      self.assertIsNone(self.service.pending)

  def test_rejected_phone_never_receives_session(self):
    self.service.device_set_home(True)
    ticket = self.service.pair(self.service.device_open()['window']['code'], 'Rejected')
    self.service.device_decide(self.service.pending['id'], False)
    self.assertEqual(self.service.status(ticket)[0]['state'], 'rejected')
    with self.assertRaises(PhoneError):
      self.service.kakao.challenge(ticket)

  def test_real_capnp_panda_list_is_copied_and_keeps_original_timestamp(self):
    from cereal import log
    event = log.Event.new_message()
    pandas = event.init('pandaStates', 1)
    for key, value in self.sm.data['pandaStates'][0].items():
      setattr(pandas[0], key, value)
    class CapnpSM(HomeSM):
      def __getitem__(inner, key):
        return event.as_reader().pandaStates if key == 'pandaStates' else super().__getitem__(key)
    self.runtime.update(CapnpSM(self.now), 10, True)
    self.assertEqual(self.runtime.home_check(), '')
    pandas[0].ignitionLine = True
    self.assertEqual(self.runtime.home_check(), '')  # immutable copied snapshot
    self.now += 1.5
    self.assertTrue(self.runtime.home_check())

  def test_started_or_ignition_transition_revokes_immediately(self):
    for name, key in (('deviceState', 'started'), ('pandaStates', 'ignitionCan')):
      self.runtime.update(HomeSM(self.now), 10, True)
      token, _ = self.connect()
      target = self.sm.data[name][0] if name == 'pandaStates' else self.sm.data[name]
      target[key] = True
      self.runtime.update(self.sm, 10, True)
      self.assertFalse(self.service.home_active)
      with self.assertRaises(PhoneError):
        self.service.session(token)
      self.sm = HomeSM(self.now)

  def test_mode_changes_clear_codes_pending_approved_tickets_and_sessions(self):
    for stage in ('code', 'pending', 'approved', 'connected'):
      for enabled in (False, True):
        self.service.device_set_home(True)
        code = self.service.device_open()['window']['code']
        ticket = self.service.pair(code, 'Android') if stage != 'code' else None
        if stage in ('approved', 'connected'):
          self.service.device_decide(self.service.pending['id'], True)
        token = self.service.status(ticket)[1] if stage == 'connected' else ticket
        self.service.device_set_home(enabled)
        self.assertFalse(self.service.sessions)
        self.assertIsNone(self.service.window)
        self.assertIsNone(self.service.pending)
        with self.assertRaises(PhoneError):
          self.service.status(token)
    self.service.device_set_home(False)
    with self.assertRaises(PhoneError):
      self.service.device_open()

  def test_vehicle_session_cannot_survive_home_transition(self):
    parked = SM(self.now)
    self.runtime.update(parked, 10, True)
    ticket = self.service.pair(self.service.device_open()['window']['code'], 'Vehicle')
    self.service.device_decide(self.service.pending['id'], True)
    _, token = self.service.status(ticket)
    self.runtime.update(HomeSM(self.now), 10, True)
    self.service.device_set_home(True)
    with self.assertRaises(PhoneError):
      self.service.session(token)

  def test_close_and_restart_cannot_reuse_home_session(self):
    token, _ = self.connect()
    self.runtime.close()
    with self.assertRaises(PhoneError):
      self.service.session(token)
    with self.assertRaises(PhoneError):
      self.service.device_set_home(True)
    restarted = PhoneRuntime(self.store, clock=lambda: self.now)
    self.addCleanup(restarted.close)
    restarted.update(HomeSM(self.now), 10, True)
    self.assertEqual(restarted.service.mode, 'vehicle')
    with self.assertRaises(PhoneError):
      restarted.service.session(token)

  def test_nonce_csrf_sequence_stop_expiry_and_disconnect(self):
    token, csrf = self.connect()
    payload = frame(self.service.kakao.challenge(token)['challenge'])
    with self.assertRaises(PhoneError):
      self.service.kakao.accept(token, 'wrong', payload)
    self.service.kakao.accept(token, csrf, payload)
    with self.assertRaises(PhoneError):
      self.service.kakao.accept(token, csrf, payload)
    payload['challenge'] = self.service.kakao.challenge(token)['challenge']
    with self.assertRaises(PhoneError):
      self.service.kakao.accept(token, csrf, payload)
    payload.update(seq=2, active=False)
    self.assertEqual(self.service.kakao.accept(token, csrf, payload)['events'], [])
    payload = frame(self.service.kakao.challenge(token)['challenge'], 3)
    self.service.kakao.accept(token, csrf, payload)
    for _ in range(3):
      self.now += 1.001
      self.runtime.update(HomeSM(self.now), 10, True)
    self.assertFalse(self.service.kakao.view()['received'])
    self.assertTrue(self.service.home_active)
    self.service.disconnect(token)
    with self.assertRaises(PhoneError):
      self.service.kakao.challenge(token)

  def test_code_and_session_expiry_with_continuous_device_telemetry(self):
    self.service.device_set_home(True)
    code = self.service.device_open()['window']['code']
    for _ in range(CODE_TTL):
      self.now += 1
      self.runtime.update(HomeSM(self.now), 10, True)
    with self.assertRaises(PhoneError):
      self.service.pair(code, 'Expired')
    token, _ = self.connect()
    for _ in range(SESSION_TTL):
      self.now += 1
      self.runtime.update(HomeSM(self.now), 10, True)
    with self.assertRaises(PhoneError):
      self.service.session(token)


class HomeHttpsTest(unittest.TestCase):
  def test_home_allowlist_and_security_over_real_tls(self):
    store, now = Store(), 100.
    runtime = PhoneRuntime(store, clock=lambda: now, allow_model_change=True)
    self.addCleanup(runtime.close)
    runtime.update(HomeSM(now), 10, True)
    service = runtime.service
    service.device_set_home(True)
    with tempfile.TemporaryDirectory(prefix='koranipilot-home-tls-') as directory:
      cert, key = ensure_tls_identity(directory, '127.0.0.1')
      transport = PhoneTransport(service, host='127.0.0.1', port=0, authority='127.0.0.1', certfile=cert, keyfile=key)
      runtime.attach(transport)
      port = transport.server.server_port
      authority = f'127.0.0.1:{port}'
      transport.server.authority = authority
      context, cookie = ssl.create_default_context(cafile=cert), ''

      def call(path, data=None, csrf='', **overrides):
        nonlocal cookie
        conn = http.client.HTTPSConnection('127.0.0.1', port, context=context, timeout=3)
        headers = {'Host': authority, 'Origin': f'https://{authority}', 'Content-Type': 'application/json',
                   'Cookie': cookie, 'X-CSRF-Token': csrf, **overrides}
        conn.request('POST' if data is not None else 'GET', '/api/phone/' + path,
                     body=json.dumps(data) if data is not None else None, headers=headers)
        reply = conn.getresponse()
        body, status = json.loads(reply.read()), reply.status
        if replacement := reply.getheader('Set-Cookie'):
          cookie = replacement.split(';')[0]
        conn.close()
        return status, body

      self.assertEqual(call('kakao')[0], 401)
      code = service.device_open()['window']['code']
      self.assertEqual(call('pair', {'code': code, 'name': 'Home'})[0], 200)
      self.assertEqual(call('kakao')[0], 401)
      self.assertEqual(call('home', {'enabled': True})[0], 404)  # local-only mode selection
      service.device_decide(service.pending['id'], True)
      status, session = call('session')
      self.assertEqual(status, 200)
      csrf = session['csrf']
      self.assertEqual(session['mode'], HOME_MODE)
      self.assertEqual(call('overview')[1]['connection']['mode'], HOME_MODE)
      for endpoint in ('changes', 'models', 'navigation', 'road/fix', 'road/sync', 'road/commit', 'road/stop'):
        with self.subTest(endpoint=endpoint):
          status, body = call(endpoint, {}, csrf)
          self.assertEqual((status, body['code']), (403, 'receive_only'))
      payload = frame(call('kakao')[1]['challenge'])
      self.assertEqual(call('kakao', payload, csrf, Origin='https://other')[0], 403)
      self.assertEqual(call('kakao', payload, csrf, Host='other')[0], 403)
      self.assertEqual(call('kakao', payload, 'wrong')[0], 403)
      self.assertEqual(call('kakao', payload, csrf)[0], 200)
      self.assertEqual(call('kakao', payload, csrf)[0], 409)
      old_cookie = cookie
      self.assertEqual(call('logout', {}, csrf)[0], 200)
      self.assertFalse(service.kakao.view()['received'])
      self.assertEqual(call('overview', Cookie=old_cookie)[0], 401)
      self.assertEqual(store.writes, [])


if __name__ == '__main__':
  unittest.main()
