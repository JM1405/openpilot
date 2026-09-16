import http.client
import json
import ssl
import tempfile
import unittest

from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_runtime import PhoneRuntime
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_transport import PhoneTransport, ensure_tls_identity


class Store:
  def __init__(self):
    self.data = {
      'AlphaLongitudinalEnabled': False, 'ExperimentalMode': True, 'Mads': True,
      'DynamicExperimentalControl': False, 'Version': '2026.2.2', 'GitBranch': 'work/phone-b1',
      'GitCommit': '1234567890abcdef', 'HardwareSerial': 'C4TEST123456',
    }
    self.writes = []

  def get(self, key):
    return self.data.get(key)

  def put_bool(self, key, value, block=True):
    self.writes.append((key, value))
    self.data[key] = value

  def put(self, key, value, block=True):
    self.writes.append((key, value))
    self.data[key] = value

  def remove(self, key):
    self.writes.append((key, None))
    self.data.pop(key, None)


class Message:
  def __init__(self, data): self.data = data
  def to_dict(self): return json.loads(json.dumps(self.data))


class SM:
  def __init__(self, now):
    self.services = {'carState', 'carControl', 'selfdriveState', 'selfdriveStateSP', 'carParams',
                     'longitudinalPlanSP', 'deviceState', 'modelManagerSP'}
    self.seen = dict.fromkeys(self.services, False)
    self.valid = dict.fromkeys(self.services, False)
    self.recv_frame = dict.fromkeys(self.services, -1)
    self.recv_time = dict.fromkeys(self.services, 0.)
    self.data = {}
    values = {
      'carState': {'canValid': True, 'vEgo': 0., 'standstill': True, 'gearShifter': 'park'},
      'carControl': {'enabled': False, 'latActive': False, 'longActive': False},
      'selfdriveState': {'enabled': False, 'experimentalMode': True},
      'selfdriveStateSP': {'mads': {'available': True, 'enabled': False, 'active': False}},
      'carParams': {'brand': 'hyundai', 'alphaLongitudinalAvailable': True, 'openpilotLongitudinalControl': False},
      'longitudinalPlanSP': {'dec': {'active': False, 'state': 'acc'}},
      'deviceState': {'deviceType': 'mici'},
      'modelManagerSP': {'activeBundle': {}, 'selectedBundle': {}, 'availableBundles': [
        {'ref': 'model/test', 'index': 7, 'displayName': '테스트 모델', 'generation': 10,
         'status': 'notDownloading', 'models': []},
      ]},
    }
    for name, data in values.items(): self.feed(name, data, now)

  def feed(self, name, data, now):
    self.data[name] = data
    self.seen[name] = self.valid[name] = True
    self.recv_frame[name] = 11
    self.recv_time[name] = now

  def __getitem__(self, key): return Message(self.data[key])


class PhoneManagementTest(unittest.TestCase):
  def setUp(self):
    self.now = 100.
    self.store, self.sm = Store(), SM(self.now)
    self.runtime = PhoneRuntime(self.store, clock=lambda: self.now)
    self.runtime.update(self.sm, 10, True)
    self.addCleanup(self.runtime.close)

  def connect(self):
    service = self.runtime.service
    ticket = service.pair(service.device_open()['window']['code'], 'Android')
    service.device_decide(service.pending['id'], True)
    state, token = service.status(ticket)
    return token, state['csrf']

  def test_overview_is_capability_filtered_and_baseline_model_is_fixed(self):
    token, _ = self.connect()
    view = self.runtime.service.management.overview()
    self.assertEqual(view['device']['hardware'], 'comma four (MICI)')
    self.assertEqual(view['device']['identifier'], '••••123456')
    rows = {row['id']: row for row in view['settings']['rows']}
    self.assertTrue(rows['owner']['supported'])
    self.assertFalse(rows['owner']['editable'])  # release candidate keeps cruise owner fixed
    self.assertTrue(rows['mads']['editable'])
    self.assertEqual(view['models']['current']['name'], 'CD210 (기본)')
    self.assertTrue(view['models']['baseline_fixed'])
    self.assertFalse(view['models']['editable'])
    self.assertEqual(self.runtime.service.view(token)['revision'], view['settings']['revision'])

  def test_setting_receipt_saved_and_actual_are_distinct(self):
    token, csrf = self.connect()
    revision = self.runtime.service.view(token)['revision']
    request = {'request_id': 'setting-request-0001', 'id': 'mads', 'value': False,
               'revision': revision, 'acknowledged': True}
    receipt = self.runtime.service.change(token, csrf, request)
    self.assertEqual(receipt['outcome'], 'saved')
    result = self.runtime.service.result(token, request['request_id'])
    self.assertFalse(result['setting']['saved'])
    self.assertTrue(result['setting']['current'])
    self.assertEqual(result['setting']['status'], '재시작 필요')
    self.assertEqual(self.runtime.service.change(token, csrf, request), receipt)
    self.assertEqual(self.store.writes.count(('Mads', False)), 1)

  def test_lost_write_acknowledgement_is_unknown_and_never_retried(self):
    token, csrf = self.connect()
    original = self.store.put_bool
    def lose_ack(*args, **kwargs):
      original(*args, **kwargs)
      raise OSError('lost')
    self.store.put_bool = lose_ack
    request = {'request_id': 'unknown-request-001', 'id': 'mads', 'value': False,
               'revision': self.runtime.service.view(token)['revision'], 'acknowledged': True}
    first = self.runtime.service.change(token, csrf, request)
    self.store.put_bool = original
    self.assertEqual(first['outcome'], 'unknown')
    self.assertEqual(self.runtime.service.change(token, csrf, request), first)
    self.assertEqual(self.store.writes.count(('Mads', False)), 1)

  def test_driving_and_expired_runtime_block_changes(self):
    token, csrf = self.connect()
    revision = self.runtime.service.view(token)['revision']
    self.sm.feed('carState', {'canValid': True, 'vEgo': 2., 'standstill': False, 'gearShifter': 'drive'}, self.now)
    self.runtime.update(self.sm, 10, True)
    receipt = self.runtime.service.change(token, csrf, {'request_id': 'blocked-request-001', 'id': 'mads',
      'value': False, 'revision': revision, 'acknowledged': True})
    self.assertEqual(receipt['outcome'], 'rejected')
    self.now += 1.
    self.assertFalse(self.runtime.controller.view()['parked'])

  def test_model_request_path_exists_but_default_candidate_rejects_it(self):
    token, csrf = self.connect()
    models = self.runtime.service.management.models()
    receipt = self.runtime.service.model_change(token, csrf, {'request_id': 'model-request-00001',
      'ref': 'model/test', 'revision': models['revision'], 'acknowledged': True})
    self.assertEqual(receipt['outcome'], 'rejected')
    self.assertEqual(receipt['code'], 'baseline_fixed')
    self.assertNotIn('ModelManager_DownloadIndex', self.store.data)

  def test_device_candidate_can_start_read_only_before_write_gate(self):
    runtime = PhoneRuntime(self.store, clock=lambda: self.now, allow_settings_change=False)
    self.addCleanup(runtime.close)
    runtime.update(self.sm, 10, True)
    service = runtime.service
    ticket = service.pair(service.device_open()['window']['code'], 'Android')
    service.device_decide(service.pending['id'], True)
    state, token = service.status(ticket)
    view = service.view(token)
    mads = next(row for row in view['rows'] if row['id'] == 'mads')
    self.assertFalse(mads['editable'])
    self.assertIn('읽기 전용', mads['blocked_reason'])
    receipt = service.change(token, state['csrf'], {'request_id': 'readonly-request-001', 'id': 'mads',
      'value': False, 'revision': view['revision'], 'acknowledged': True})
    self.assertEqual(receipt['outcome'], 'rejected')
    self.assertFalse(self.store.writes)

  def test_later_opt_in_model_request_stays_separate_from_applied(self):
    runtime = PhoneRuntime(self.store, clock=lambda: self.now, allow_model_change=True)
    self.addCleanup(runtime.close)
    runtime.update(self.sm, 10, False)
    service = runtime.service
    ticket = service.pair(service.device_open()['window']['code'], 'Android')
    service.device_decide(service.pending['id'], True)
    state, token = service.status(ticket)
    models = service.management.models()
    request = {'request_id': 'model-request-00002', 'ref': 'model/test',
               'revision': models['revision'], 'acknowledged': True}
    receipt = service.model_change(token, state['csrf'], request)
    self.assertEqual(receipt['outcome'], 'requested')
    self.assertEqual(self.store.data['ModelManager_DownloadIndex'], 7)
    self.assertFalse(service.model_result(token, request['request_id'])['applied'])
    self.store.data.pop('ModelManager_DownloadIndex')
    self.sm.feed('modelManagerSP', {'activeBundle': {'ref': 'model/test', 'index': 7,
      'displayName': '테스트 모델', 'generation': 10, 'status': 'downloaded', 'models': []},
      'selectedBundle': {}, 'availableBundles': self.sm.data['modelManagerSP']['availableBundles']}, self.now)
    runtime.update(self.sm, 10, False)
    self.assertTrue(service.model_result(token, request['request_id'])['applied'])


class HttpsOverviewTest(unittest.TestCase):
  def test_real_tls_pair_approval_overview_and_logout(self):
    now = 100.
    store, sm = Store(), SM(now)
    runtime = PhoneRuntime(store, clock=lambda: now)
    runtime.update(sm, 10, True)
    self.addCleanup(runtime.close)
    with tempfile.TemporaryDirectory(prefix='koranipilot-phone-tls-') as directory:
      cert, key = ensure_tls_identity(directory, '127.0.0.1')
      transport = PhoneTransport(runtime.service, host='127.0.0.1', port=0, authority='127.0.0.1', certfile=cert, keyfile=key)
      runtime.attach(transport)
      port = transport.server.server_port
      authority = f'127.0.0.1:{port}'
      transport.server.authority = authority
      context = ssl.create_default_context(cafile=cert)
      cookie = ''
      def call(path, data=None, csrf=''):
        nonlocal cookie
        conn = http.client.HTTPSConnection('127.0.0.1', port, context=context, timeout=3)
        headers = {'Host': authority, 'Origin': 'https://' + authority, 'Content-Type': 'application/json',
                   'Cookie': cookie, 'X-CSRF-Token': csrf}
        conn.request('POST' if data is not None else 'GET', '/api/phone/' + path,
                     body=json.dumps(data) if data is not None else None, headers=headers)
        response = conn.getresponse()
        body = json.loads(response.read())
        replacement = response.getheader('Set-Cookie')
        if replacement is not None: cookie = replacement.split(';')[0]
        status = response.status
        conn.close()
        return status, body
      self.assertEqual(call('overview')[0], 401)
      self.assertEqual(call('kakao')[0], 401)
      code = runtime.service.device_open()['window']['code']
      self.assertEqual(call('pair', {'code': code, 'name': 'Android'})[0], 200)
      runtime.service.device_decide(runtime.service.pending['id'], True)
      status, session = call('session')
      self.assertEqual(status, 200)
      status, overview = call('overview')
      self.assertEqual(status, 200)
      self.assertEqual(overview['device']['product'], 'Koranipilot')
      from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_kakao import frame
      status, challenge = call('kakao')
      self.assertEqual(status, 200)
      body = frame(challenge['challenge'])
      self.assertEqual(call('kakao', body, 'wrong-csrf')[0], 403)
      status, received = call('kakao', body, session['csrf'])
      self.assertEqual(status, 200)
      self.assertEqual(received['events'][0]['kind'], 'sharp_turn')
      self.assertFalse(received['control_enabled'])
      self.assertEqual(call('kakao', body, session['csrf'])[0], 409)
      self.assertEqual(call('logout', {}, session['csrf'])[0], 200)
      self.assertEqual(call('overview')[0], 401)
      self.assertEqual(call('kakao')[0], 401)
      self.assertFalse(runtime.service.kakao.view()['received'])


if __name__ == '__main__':
  unittest.main()
