"""Real loopback HTTP/file transactions with synthetic Params; never execute model bytes."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from cereal import custom, log
from openpilot.sunnypilot.models.manager import ModelManagerSP
from openpilot.sunnypilot.models.selection import REQUEST, RESULT, artifact_manifest, bundle_signature
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_management import Store


class ModelTransactionTest(unittest.TestCase):
  def setUp(self):
    self.store = Store()
    self.store.data['IsOnroad'] = True
    self.store.data['TestParked'] = True
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.path_patch = patch('openpilot.sunnypilot.models.helpers.Paths.model_root', return_value=str(self.root))
    self.path_patch.start()
    self.addCleanup(self.path_patch.stop)
    self.payload = b'verified test model bytes' * 20000
    self.action = lambda: None
    self.chunked = False
    self.failure = False
    self.requests = 0
    fixture = self
    class Handler(BaseHTTPRequestHandler):
      def log_message(self, *_): pass
      def do_GET(self):
        fixture.requests += 1
        fixture.action()
        if fixture.failure:
          self.send_error(503); return
        if self.path.endswith('.chunkmanifest'):
          if not fixture.chunked:
            self.send_error(404); return
          data = b'2'
        elif '.chunk01of02' in self.path:
          data = fixture.payload[:len(fixture.payload)//2]
        elif '.chunk02of02' in self.path:
          data = fixture.payload[len(fixture.payload)//2:]
        else:
          data = fixture.payload
        self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers()
        try: self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError): pass
    self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=self.server.serve_forever, daemon=True).start()
    self.addCleanup(self.server.server_close)
    self.addCleanup(self.server.shutdown)
    digest = hashlib.sha256(self.payload).hexdigest()
    self.bundle = custom.ModelManagerSP.ModelBundle(**{
      'index': 7, 'ref': 'fixture/new', 'displayName': 'Fixture', 'minimumSelectorVersion': 15,
      'runner': 'tinygrad', 'generation': 10, 'models': [{'type': 'supercombo', 'artifact': {
        'fileName': 'new.pkl', 'downloadUri': {'uri': f'http://127.0.0.1:{self.server.server_port}/new.pkl', 'sha256': digest}}}]})
    self.old = self.bundle.to_dict()
    self.old['ref'] = 'fixture/old'
    self.old['models'][0]['artifact']['fileName'] = 'old.pkl'
    self.old['models'][0]['artifact']['downloadUri']['sha256'] = hashlib.sha256(b'old valid model').hexdigest()
    self.store.data['ModelManager_ActiveBundle'] = self.old
    (self.root/'old.pkl').write_bytes(b'old valid model')
    class Publisher:
      def send(self, *_): pass
    self.manager = ModelManagerSP(self.store, Publisher(), parked=lambda: self.store.get('IsOnroad') is True and self.store.get('TestParked') is True)
    self.manager.available_models = [self.bundle]
    self.manager.model_fetcher.get_available_bundles = lambda: [self.bundle]
    self.queue()

  def queue(self, nonce='request1'):
    self.store.put(REQUEST, {'id': nonce, 'index': 7, 'ref': self.bundle.ref, 'signature': bundle_signature(self.bundle)})
    self.store.put('ModelManager_DownloadIndex', 7)

  def run_manager(self):
    self.manager.run_once(str(self.root))

  def old_preserved(self):
    self.assertEqual(self.store.get('ModelManager_ActiveBundle'), self.old)
    self.assertEqual((self.root/'old.pkl').read_bytes(), b'old valid model')
    self.assertFalse(list(self.root.glob('.download-*')))

  def test_http_verified_commit_and_cached_retry(self):
    self.run_manager()
    self.assertEqual(self.store.get('ModelManager_ActiveBundle')['ref'], 'fixture/new')
    self.assertEqual(self.store.get(RESULT)['state'], 'ready')
    self.assertEqual((self.root/'new.pkl').read_bytes(), self.payload)
    self.assertIsNone(self.store.get(REQUEST))
    count = self.requests
    self.queue('retry'); self.run_manager()
    self.assertEqual(count, self.requests)

  def test_chunked_verified_and_stale_manifest_replaced(self):
    self.chunked = True
    (self.root/'new.pkl.chunkmanifest').write_text('1')
    (self.root/'new.pkl.chunk01of01').write_bytes(b'outdated cache')
    self.run_manager()
    self.assertEqual(self.store.get(RESULT)['state'], 'ready')
    self.assertEqual((self.root/'new.pkl').read_bytes(), self.payload)
    self.assertFalse((self.root/'new.pkl.chunkmanifest').exists())

  def test_hash_failure_preserves_active_and_is_persistent(self):
    self.payload = b'corrupt response'
    self.run_manager(); self.old_preserved()
    self.assertEqual(self.store.get(RESULT)['state'], 'failed')
    self.assertIsNone(self.store.get('ModelManager_DownloadIndex'))
    self.run_manager()
    self.assertEqual(self.store.get(RESULT)['state'], 'failed')

  def test_http_failure_does_not_fall_back_or_mutate_active(self):
    self.failure = True
    self.run_manager(); self.old_preserved()
    self.assertEqual(self.requests, 1)
    self.assertEqual(self.store.get(RESULT)['state'], 'failed')

  def test_driving_does_no_fetch_download_or_write(self):
    self.store.data['TestParked'] = False
    self.manager.model_fetcher.get_available_bundles = lambda: self.fail('onroad fetch')
    before = dict(self.store.data)
    self.run_manager(); self.old_preserved()
    self.assertEqual(self.store.data, before)
    self.assertEqual(self.requests, 0)

  def test_missing_onroad_state_fails_closed(self):
    self.store.data.pop('IsOnroad')
    self.run_manager(); self.old_preserved()
    self.assertEqual(self.requests, 0)

  def test_leaving_park_during_transfer_defers_without_losing_request(self):
    self.action = lambda: self.store.put('TestParked', False)
    self.run_manager(); self.old_preserved()
    self.assertEqual(self.store.get('ModelManager_DownloadIndex'), 7)
    self.action = lambda: None
    self.store.put('TestParked', True); self.run_manager()
    self.assertEqual(self.store.get(RESULT)['state'], 'ready')

  def test_cancel_during_transfer_never_commits(self):
    def cancel():
      self.store.remove('ModelManager_DownloadIndex'); self.store.remove(REQUEST)
    self.action = cancel
    self.run_manager(); self.old_preserved()
    self.assertIsNone(self.store.get(RESULT))

  def test_new_request_same_index_survives_old_completion(self):
    self.action = lambda: self.queue('new-request')
    self.run_manager(); self.old_preserved()
    self.assertEqual(self.store.get(REQUEST)['id'], 'new-request')
    self.assertEqual(self.store.get('ModelManager_DownloadIndex'), 7)
    self.assertIsNone(self.store.get(RESULT))

  def test_catalogue_changed_after_selection_rejected(self):
    self.bundle.generation = 11
    self.run_manager(); self.old_preserved()
    self.assertEqual(self.store.get(RESULT)['state'], 'failed')
    self.assertEqual(self.requests, 0)

  def test_active_filename_collision_rejected_before_network(self):
    self.bundle.models[0].artifact.fileName = 'old.pkl'; self.queue()
    self.run_manager(); self.old_preserved()
    self.assertEqual(self.requests, 0)
    self.assertEqual(self.store.get(RESULT)['state'], 'failed')

  def test_path_escape_rejected(self):
    self.bundle.models[0].artifact.fileName = '../escape'; self.queue()
    self.run_manager(); self.old_preserved()
    self.assertEqual(self.requests, 0)

  def test_cache_hit_also_rechecks_cancellation_before_commit(self):
    (self.root/'new.pkl').write_bytes(self.payload)
    report = self.manager._report_status
    def cancel_at_report():
      self.store.remove('ModelManager_DownloadIndex'); report()
    with patch.object(self.manager, '_report_status', cancel_at_report): self.run_manager()
    self.old_preserved()

  def test_inference_identity_schema_roundtrip(self):
    from cereal import messaging
    from openpilot.sunnypilot.modeld_v2.modeld_base import ModelStateBase
    model = object.__new__(ModelStateBase)
    model.model_ref, model.model_name = self.bundle.ref, self.bundle.displayName
    model.model_identity_known, model.model_signature = True, bundle_signature(self.bundle)
    message = messaging.new_message('modelDataV2SP')
    model.report_model_identity(message)
    with log.Event.from_bytes(message.to_bytes()) as result:
      self.assertTrue(result.valid)
      self.assertEqual(result.modelDataV2SP.modelSignature, model.model_signature)
      self.assertEqual(result.modelDataV2SP.modelRef, self.bundle.ref)

  def test_phone_approval_to_download_and_inference_receipt(self):
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_runtime import PhoneRuntime
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_management import SM
    self.store.remove('ModelManager_DownloadIndex'); self.store.remove(REQUEST)
    sm = SM(100.)
    sm.data['modelManagerSP']['availableBundles'] = [self.bundle.to_dict()]
    runtime = PhoneRuntime(self.store, clock=lambda: 100., allow_model_change=True)
    self.addCleanup(runtime.close)
    runtime.update(sm, 10, False)
    service = runtime.service
    ticket = service.pair(service.device_open()['window']['code'], 'Fixture phone')
    service.device_decide(service.pending['id'], True)
    state, token = service.status(ticket)
    receipt = service.model_change(token, state['csrf'], {'request_id': 'fixture-model-001',
      'ref': self.bundle.ref, 'revision': service.management.models()['revision'], 'acknowledged': True})
    self.assertEqual(receipt['outcome'], 'requested')
    self.run_manager()
    self.assertEqual(self.store.get(RESULT)['state'], 'ready')
    sm.data['modelManagerSP']['activeBundle'] = self.store.get('ModelManager_ActiveBundle')
    runtime.update(sm, 10, False)
    self.assertFalse(service.model_result(token, 'fixture-model-001')['applied'])
    sm.feed('modelDataV2SP', {'modelRef': self.bundle.ref, 'modelName': self.bundle.displayName,
      'modelIdentityKnown': True, 'modelSignature': bundle_signature(self.bundle)}, 100.)
    runtime.update(sm, 10, False)
    self.assertTrue(service.model_result(token, 'fixture-model-001')['applied'])


class ParkedGuardTest(unittest.TestCase):
  def test_fresh_vehicle_state_required_on_every_check(self):
    from openpilot.sunnypilot.models.selection import ParkedDownloadGuard
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_management import SM
    store, sm = Store(), SM(100.)
    store.data['IsOnroad'] = True
    sm.frame = 11
    sm.update = lambda _: None
    sm.feed('deviceState', {'started': True}, 100.)
    guard = object.__new__(ParkedDownloadGuard)
    guard.params, guard.sm, guard.started, guard.started_frame = store, sm, False, 0
    with patch('time.monotonic', return_value=100.):
      self.assertTrue(guard())
      sm.data['carState']['gearShifter'] = 'drive'
      self.assertFalse(guard())
      sm.data['carState']['gearShifter'] = 'park'
      sm.data['carControl']['latActive'] = True
      self.assertFalse(guard())
      sm.data['carControl']['latActive'] = False
      sm.data['selfdriveStateSP']['mads']['active'] = True
      self.assertFalse(guard())
      sm.data['selfdriveStateSP']['mads']['active'] = False
      self.assertTrue(guard())
    with patch('time.monotonic', return_value=100.6):
      self.assertFalse(guard())
    with patch('time.monotonic', return_value=100.):
      store.data['IsOnroad'] = False
      self.assertFalse(guard())


class NativeStorageTest(unittest.TestCase):
  def test_new_params_are_registered_and_isolated(self):
    from openpilot.common.params import Params
    from openpilot.sunnypilot.models.selection import selection_lock
    with tempfile.TemporaryDirectory(prefix='d293-native-params-') as directory:
      params = Params(directory)
      with selection_lock(params):
        params.put(REQUEST, {'id': 'native-fixture', 'index': 7}, block=True)
        params.put(RESULT, {'state': 'queued'}, block=True)
      self.assertEqual(params.get(REQUEST)['id'], 'native-fixture')
      self.assertEqual(params.get(RESULT)['state'], 'queued')
      params.remove(REQUEST)
      self.assertIsNone(params.get(REQUEST))
