import json
import unittest  # noqa: TID251 - shares the existing transport/runtime fixtures
import tempfile
from pathlib import Path

from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_catalog import CATALOG, SPECS
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_runtime import PhoneRuntime
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError
from openpilot.selfdrive.ui.sunnypilot.mici.korean.settings import SettingsError
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_management import Store, SM
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_home import HomeSM


class CatalogTest(unittest.TestCase):
  def setUp(self):
    self.now = 100.
    self.store, self.sm = Store(), SM(self.now)
    self.sm.services.add('carParamsSP')
    self.sm.feed('carParamsSP', {'intelligentCruiseButtonManagementAvailable': True}, self.now)
    self.sm.data['carParams'].update(openpilotLongitudinalControl=True, steerControlType='torque', enableBsm=True, pcmCruise=False)
    self.store.data.update(IsMetric=True, CompletedSunnylinkConsentVersion='1.0')
    self.runtime = PhoneRuntime(self.store, clock=lambda: self.now)
    self.runtime.update(self.sm, 10, False)
    self.service, self.catalog = self.runtime.service, self.runtime.service.catalog
    self.addCleanup(self.runtime.close)

  def connect(self):
    ticket = self.service.pair(self.service.device_open()['window']['code'], 'Catalog test')
    self.service.device_decide(self.service.pending['id'], True)
    state, token = self.service.status(ticket)
    return token, state['csrf']

  def view(self):
    return self.catalog.view()

  def save(self, name, value, **kw):
    return self.catalog.save(name, value, self.view()['revision'], acknowledged=True, **kw)

  def request(self, name='OnroadScreenOffBrightness', value=7):
    return dict(request_id='catalog-request-0001', id=name, value=value, revision=self.view()['revision'], acknowledged=True)

  def test_catalog_is_complete_unique_and_under_phone_response_budget(self):
    view = self.view()
    self.assertEqual(len(view['rows']), 74)
    self.assertEqual(len(SPECS), len(CATALOG['rows']))
    self.assertEqual(len(view['groups']), 10)
    self.assertLess(len(json.dumps(view, ensure_ascii=False).encode()), 65536)
    self.assertEqual(self.store.writes, [])

  def test_all_supported_values_use_exact_allowlisted_storage_and_never_claim_runtime(self):
    count = 0
    for name, spec in SPECS.items():
      with self.subTest(name=name):
        original = dict(self.store.data)
        try:
          for key, values in spec.get('requires', {}).items():
            self.store.data[key] = values[0]
          if spec.get('excludes'):
            self.store.data[spec['excludes']] = False
          row = next(r for r in self.view()['rows'] if r['id'] == name)
          if not row['editable']:
            continue
          values = [o['value'] for o in spec['options']] if 'options' in spec else [spec['min'], spec['max']]
          for value in values:
            before = len(self.store.writes)
            self.save(name, value)
            self.assertEqual(self.store.writes[before:], [(spec['key'], value)])
            updated = next(r for r in self.view()['rows'] if r['id'] == name)
            self.assertEqual(updated['saved'], value)
            if name not in ('owner', 'mode', 'mads'):
              self.assertIsNone(updated['current'])
            count += 1
        finally:
          self.store.data = original
    self.assertGreater(count, 145)

  def test_integer_boolean_float_ranges_and_steps_are_not_coerced(self):
    for name, value in [('IsMetric', 1), ('InteractivityTimeout', True), ('InteractivityTimeout', 11),
                        ('InteractivityTimeout', 130), ('MadsSteeringMode', '1'), ('MadsSteeringMode', 8),
                        ('TorqueParamsOverrideFriction', float('nan')), ('TorqueParamsOverrideFriction', .015),
                        ('TorqueParamsOverrideLatAccelFactor', float('inf')), ('TorqueParamsOverrideFriction', 10**500),
                        ('QuietMode', None), ('NoSuchParam', True)]:
      with self.subTest(name=name, value=value), self.assertRaises(SettingsError):
        self.save(name, value)
    self.assertEqual(self.store.writes, [])

  def test_numeric_revisions_include_unit_changes(self):
    revision = self.view()['revision']
    self.store.data['IsMetric'] = False
    with self.assertRaisesRegex(SettingsError, '새로고침'):
      self.catalog.save('BlinkerMinLateralControlSpeed', 40, revision, acknowledged=True)
    self.assertEqual(self.store.writes, [])

  def test_parent_and_mutually_exclusive_choices_rechecked_at_save(self):
    self.store.data['NeuralNetworkLateralControl'] = True
    with self.assertRaisesRegex(SettingsError, '먼저 끄기'):
      self.save('EnforceTorqueControl', True)
    self.store.data['NeuralNetworkLateralControl'] = False
    self.store.data['EnforceTorqueControl'] = True
    with self.assertRaisesRegex(SettingsError, '직접 튜닝'):
      self.save('TorqueParamsOverrideFriction', .2)
    self.store.data['CustomTorqueParams'] = True
    self.save('TorqueParamsOverrideFriction', .2)
    self.assertEqual(self.store.writes, [('TorqueParamsOverrideFriction', .2)])

  def test_all_writes_refuse_stale_driving_active_unknown_and_readonly(self):
    for case in ('stale', 'driving', 'active', 'unknown', 'readonly'):
      with self.subTest(case=case):
        self.now = 100.
        sm = SM(self.now)
        if case == 'driving':
          sm.data['carState'].update(gearShifter='drive', standstill=False, vEgo=1.)
        if case == 'active':
          sm.data['carControl']['latActive'] = True
        if case == 'unknown':
          sm.valid['carState'] = False
        self.runtime.update(sm, 10, False)
        self.runtime.controller.write_enabled = case != 'readonly'
        if case == 'stale':
          self.now += .51
        with self.assertRaises(SettingsError):
          self.save('QuietMode', True)
        self.assertEqual(self.store.writes, [])

  def test_home_catalog_is_readable_but_every_setting_stays_receive_only(self):
    self.runtime.update(HomeSM(self.now), 10, True)
    self.service.device_set_home(True)
    token, csrf = self.connect()
    view = self.service.catalog_view(token)
    self.assertEqual(len(view['rows']), 74)
    self.assertTrue(all(not r['editable'] for r in view['rows']))
    for name in SPECS:
      with self.subTest(name=name), self.assertRaises(PhoneError) as caught:
        self.service.change(token, csrf, self.request(name, True), catalog=True)
      self.assertEqual(caught.exception.code, 'receive_only')
    self.assertEqual(self.store.writes, [])

  def test_capabilities_never_guess_or_unlock_missing_c4_features(self):
    for name in ('TorqueBar', 'AutoLaneChangeTimer', 'QuickBootToggle', 'LateralManeuverMode'):
      with self.subTest(name=name), self.assertRaises(SettingsError):
        self.save(name, 0 if name == 'AutoLaneChangeTimer' else True)
    self.sm.data['carParams']['steerControlType'] = 'angle'
    self.runtime.update(self.sm, 10, False)
    with self.assertRaises(SettingsError):
      self.save('EnforceTorqueControl', True)
    self.assertEqual(self.store.writes, [])

  def test_icbm_uses_current_cp_sp_and_cruise_owner(self):
    self.sm.data['carParams']['openpilotLongitudinalControl'] = False
    self.runtime.update(self.sm, 10, False)
    self.save('IntelligentCruiseButtonManagement', True)
    self.save('SmartCruiseControlVision', True)
    self.sm.valid['carParamsSP'] = False
    self.runtime.update(self.sm, 10, False)
    with self.assertRaises(SettingsError):
      self.save('SmartCruiseControlMap', True)

  def test_limit_assist_choice_requires_confirmed_cruise_control(self):
    self.sm.data['carParams']['openpilotLongitudinalControl'] = False
    self.runtime.update(self.sm, 10, False)
    self.save('SpeedLimitMode', 1)
    with self.assertRaises(SettingsError):
      self.save('SpeedLimitMode', 3)

  def test_storage_failure_is_unknown_and_receipt_is_never_retried(self):
    token, csrf = self.connect()
    original = self.store.put
    def lose_ack(*args, **kwargs):
      original(*args, **kwargs)
      raise OSError('lost acknowledgement')
    self.store.put = lose_ack
    request = self.request()
    receipt = self.service.change(token, csrf, request, catalog=True)
    self.assertEqual(receipt['outcome'], 'unknown')
    self.store.put = original
    self.assertEqual(self.service.change(token, csrf, request, catalog=True), receipt)
    self.assertEqual(self.store.writes, [('OnroadScreenOffBrightness', 7)])
    self.assertEqual(self.service.result(token, request['request_id'], catalog=True)['receipt'], receipt)

  def test_success_and_conflicts_have_session_owned_receipts(self):
    token, csrf = self.connect()
    request = self.request()
    receipt = self.service.change(token, csrf, request, catalog=True)
    self.assertEqual(receipt['outcome'], 'saved')
    with self.assertRaises(PhoneError):
      self.service.change(token, csrf, {**request, 'value': 8}, catalog=True)
    with self.assertRaises(PhoneError):
      self.service.change(token, csrf, request)
    other, _ = self.connect()
    with self.assertRaises(PhoneError):
      self.service.result(other, request['request_id'], catalog=True)
    self.store.data['OnroadScreenOffBrightness'] = 8
    self.assertTrue(self.service.result(token, request['request_id'], catalog=True)['superseded'])

  def test_bad_optional_param_does_not_invent_an_off_value_or_allow_writes(self):
    self.store.data['TorqueParamsOverrideFriction'] = 'invalid'
    rows = {r['id']: r for r in self.view()['rows']}
    self.assertTrue(rows['TorqueParamsOverrideFriction']['read_error'])
    self.assertIsNone(rows['TorqueParamsOverrideFriction']['saved'])
    self.assertTrue(all(not r['editable'] for r in rows.values()))
    with self.assertRaises(SettingsError):
      self.save('QuietMode', True)

  def test_consent_and_fleet_lock_are_not_bypassed(self):
    self.store.data['CompletedSunnylinkConsentVersion'] = '0'
    with self.assertRaisesRegex(SettingsError, '동의'):
      self.save('SunnylinkEnabled', True)
    self.store.data['RecordFrontLock'] = True
    with self.assertRaisesRegex(SettingsError, '잠김'):
      self.save('RecordFront', True)
    self.assertEqual(self.store.writes, [])

  def test_csrf_approval_and_confirmation_cannot_be_skipped(self):
    token, csrf = self.connect()
    with self.assertRaises(PhoneError):
      self.service.catalog_view('invalid')
    with self.assertRaises(PhoneError):
      self.service.change(token, 'invalid', self.request(), catalog=True)
    result = self.service.change(token, csrf, {**self.request(), 'acknowledged': False}, catalog=True)
    self.assertEqual(result['code'], 'confirmation_required')
    self.assertEqual(self.store.writes, [])

  def test_quickboot_uses_fixed_path_checks_and_reads_back_file_and_param(self):
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / 'prebuilt'
      self.catalog.quickboot_path = path
      with self.assertRaises(SettingsError):
        self.save('QuickBootToggle', True)
      self.assertFalse(path.exists())
      self.store.data.update(ShowAdvancedControls=True, DisableUpdates=True)
      self.save('QuickBootToggle', True)
      self.assertTrue(path.is_file())
      self.assertIs(self.store.data['QuickBootToggle'], True)
      self.save('QuickBootToggle', False)
      self.assertFalse(path.exists())
      target = Path(directory) / 'untouched'
      target.write_text('keep')
      path.symlink_to(target)
      with self.assertRaises(SettingsError):
        self.save('QuickBootToggle', True)
      self.assertEqual(target.read_text(), 'keep')
      self.assertIs(self.store.data['QuickBootToggle'], False)
      path.unlink()
      self.runtime.update(self.sm, 10, True)
      with self.assertRaises(SettingsError):
        self.save('QuickBootToggle', True)
      self.assertFalse(path.exists())
