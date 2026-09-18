import math
import unittest
from dataclasses import replace
from unittest.mock import Mock

from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_road_input import PhoneRoadInput
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError, PhoneSettings
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.contract import RoadInputValidator
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.live import LiveRoadAdapter, NS
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.tests import test_offline as fixtures
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.tests.test_offline import TODAY, link, point

STREAM = "11111111-1111-4111-8111-111111111111"


class Fixture:
  def init_live(self):
    self.now = 100.0
    self.service = PhoneSettings(Mock(view=lambda: {"parked": True}), clock=lambda: self.now)
    self.api = PhoneRoadInput(self.service, clock=lambda: self.now)
    self.token, self.csrf = self.pair()
    self.sync_seq = self.seq = 0
    self.sync = None

  def pair(self):
    token = self.service.pair(self.service.device_open()['window']['code'], 'test')
    self.service.device_decide(self.service.pending['id'], True)
    state, token = self.service.status(token)
    return token, state['csrf']

  def send(self, action, data):
    return self.api.accept(self.token, self.csrf, action, {"schema": 1, **data})

  def synchronize(self, *, offset=90.0, rtt=0.04):
    self.sync_seq += 1
    self.sync = self.send('sync', {"stream": STREAM, "sync_sequence": self.sync_seq, "phone_send_ns": round((self.now - offset - rtt / 2) * NS)})['sync_id']
    self.now += rtt / 2 + 0.005
    return self.send('commit', {"sync_id": self.sync, "phone_receive_ns": round((self.now - 0.005 - offset) * NS)})

  def packet(self, x=20.0, **changes):
    self.seq += 1
    observed = round((self.now - 90.0 - 0.06) * NS)
    return dict(
      sync_id=self.sync,
      stream=STREAM,
      sequence=self.seq,
      fix_elapsed_ns=observed,
      received_elapsed_ns=observed + 10_000_000,
      sent_elapsed_ns=observed + 20_000_000,
      longitude=point(x)[0],
      latitude=point(x)[1],
      bearing_deg=90.0,
      speed_mps=20.0,
      accuracy_m=2.0,
      bearing_accuracy_deg=5.0,
      provider='gps',
      mock=False,
      **changes,
    )

  def receive(self, x=20.0, **changes):
    self.now += 0.1
    data = self.packet(x)
    data.update(changes)
    return self.send('fix', data)

  def rejects(self, action, packet, code):
    with self.assertRaises(PhoneError) as ctx:
      self.send(action, packet)
    self.assertEqual(ctx.exception.code, code)
    self.assertIsNone(self.api.sample().fix)


class LiveTests(Fixture, unittest.TestCase):
  def setUp(self):
    self.init_live()

  def test_clock_interval_handles_different_boot_times_and_preserves_age(self):
    response = self.synchronize()
    self.assertEqual(response['offset_min_ns'], 89_980_000_000)
    self.assertEqual(response['offset_max_ns'], 90_020_000_000)
    receipt = self.receive()
    self.assertGreater(receipt['age_upper_ms'], 80)
    self.assertAlmostEqual(self.api.sample().fix.observed_at, self.now - 0.06, places=7)

  def test_missing_heading_is_only_accepted_for_low_speed_and_does_not_renew_age(self):
    self.synchronize()
    self.receive(speed_mps=0.0, bearing_deg=None, bearing_accuracy_deg=None)
    sample = self.api.sample()
    self.assertIsNone(sample.fix.bearing_deg)
    self.assertIsNone(sample.fix.bearing_accuracy_deg)
    self.assertAlmostEqual(sample.fix.observed_at, self.now - 0.06, places=7)
    self.now += 0.15
    self.assertIsNone(self.api.sample().fix)
    self.now += 0.1
    data = self.packet()
    data.update(speed_mps=2.0, bearing_deg=None, bearing_accuracy_deg=None)
    self.rejects('fix', data, 'missingOrInvalidMeasurement')

  def test_low_speed_does_not_relax_position_quality_or_accept_invalid_heading(self):
    self.synchronize()
    for change, error in (
      ({'accuracy_m': 16.0}, 'uncertainFix'),
      ({'bearing_deg': True}, 'missingOrInvalidMeasurement'),
      ({'bearing_accuracy_deg': math.nan}, 'missingOrInvalidMeasurement'),
    ):
      self.now += 0.1
      data = self.packet()
      data.update(speed_mps=0.0, **change)
      self.rejects('fix', data, error)

  def test_asymmetric_delay_cannot_make_a_stale_fix_fresh(self):
    self.synchronize()
    self.now += 0.3
    p = self.packet()
    p['fix_elapsed_ns'] -= 130_000_000  # Nominal age 190ms, worst case > 210ms.
    self.rejects('fix', p, 'staleFix')

  def test_slow_sync_and_delayed_commit_are_rejected(self):
    for rtt, delay in ((0.12, 0.06), (0.04, 0.6)):
      self.sync_seq += 1
      sync = self.send('sync', {"stream": STREAM, "sync_sequence": self.sync_seq, "phone_send_ns": 10 * NS})['sync_id']
      self.now += delay
      self.rejects('commit', {"sync_id": sync, "phone_receive_ns": round((10 + rtt) * NS)}, 'uncertainClock')

  def test_sync_is_single_use_and_new_probe_invalidates_old_probe(self):
    self.synchronize()
    old = self.sync
    self.rejects('commit', {"sync_id": old, "phone_receive_ns": 11 * NS}, 'unknownSync')
    self.synchronize()
    self.receive()
    self.now += 0.1
    p = self.packet()
    p['sync_id'] = old
    self.rejects('fix', p, 'syncRequired')

  def test_duplicate_out_of_order_and_sequence_gap(self):
    self.synchronize()
    self.now += 0.1
    p = self.packet()
    self.send('fix', p)
    self.rejects('fix', p, 'fixReplay')
    self.receive(sequence=3)
    generation = self.api.sample().generation
    self.now += 0.1
    self.rejects('fix', p, 'fixReplay')
    self.receive(sequence=6)
    self.assertGreater(self.api.sample().generation, generation)

  def test_silence_expires_from_fix_age_and_reading_cannot_renew_it(self):
    self.synchronize()
    self.receive()
    observed = self.api.sample().fix.observed_at
    self.now += 0.1
    self.assertEqual(self.api.sample().fix.observed_at, observed)
    self.now += 0.03
    self.assertIsNone(self.api.sample().fix)
    self.assertEqual(self.api.view()['status'], 'awaitingNextFix')
    self.assertIsNotNone(self.api.sample().anchor)
    self.now += 1.3
    self.assertIsNone(self.api.sample().anchor)

  def test_clock_mapping_expires_even_with_ongoing_fixes(self):
    self.synchronize()
    for _ in range(48):
      self.receive()
    self.now += 0.3
    self.rejects('fix', self.packet(), 'syncRequired')

  def test_compatible_sync_preserves_original_deadline_but_rejects_old_epoch(self):
    self.synchronize()
    self.receive()
    before = self.api.sample()
    old_packet = self.packet()
    self.synchronize()
    after = self.api.sample()
    self.assertEqual(after.fix, before.fix)
    self.assertEqual(after.anchor, before.anchor)
    self.assertEqual(after.anchor_until_ns, before.anchor_until_ns)
    self.assertEqual(after.generation, before.generation)
    self.rejects('fix', old_packet, 'syncRequired')
    self.assertIsNone(self.api.sample().anchor)

  def test_clock_step_revokes_anchor_and_road_confirmation(self):
    self.synchronize()
    self.receive()
    generation = self.api.sample().generation
    self.synchronize(offset=89.0)
    self.assertIsNone(self.api.sample().anchor)
    self.assertGreater(self.api.sample().generation, generation)

  def test_schema_bool_clock_future_missing_mock_and_quality_clear_previous(self):
    cases = [
      ({'schema': True}, 'invalidLiveRecord'),
      ({'sequence': True}, 'invalidClockOrSequence'),
      ({'sent_elapsed_ns': -1}, 'invalidClockOrSequence'),
      ({'accuracy_m': None}, 'missingOrInvalidMeasurement'),
      ({'longitude': math.nan}, 'missingOrInvalidMeasurement'),
      ({'mock': True}, 'untrustedLocation'),
      ({'provider': 'network'}, 'untrustedLocation'),
      ({'accuracy_m': 16.0}, 'uncertainFix'),
      ({'bearing_accuracy_deg': 21.0}, 'uncertainFix'),
    ]
    self.synchronize()
    for changes, code in cases:
      with self.subTest(code=code, changes=changes):
        self.receive()
        self.now += 0.1
        data = self.packet()
        data.update(changes)
        self.rejects('fix', data, code)

  def test_future_packet_or_phone_clock_reset_is_not_mapped_as_now(self):
    self.synchronize()
    self.receive()
    for delta, code in ((NS, 'futureFix'), (-10 * NS, 'fixReplay')):
      self.now += 0.1
      p = self.packet()
      for field in ('fix_elapsed_ns', 'received_elapsed_ns', 'sent_elapsed_ns'):
        p[field] += delta
      self.rejects('fix', p, code)

  def test_receiver_clock_reversal_invalidates_sync(self):
    self.synchronize()
    self.receive()
    self.now -= 1.0
    self.assertIsNone(self.api.sample().fix)
    self.assertIsNone(self.api.receiver.mapping)

  def test_logout_expiry_and_app_restart_require_new_auth_and_sync(self):
    self.synchronize()
    self.receive()
    old_token, old_csrf = self.token, self.csrf
    self.service.disconnect(self.token)
    self.assertIsNone(self.api.sample().fix)
    self.token, self.csrf = self.pair()
    self.synchronize()
    self.receive()
    with self.assertRaises(PhoneError):
      self.api.accept(old_token, old_csrf, 'fix', {'schema': 1, **self.packet()})
    self.now += 1801
    self.assertIsNone(self.api.sample().fix)

  def test_second_authorized_phone_cannot_take_over_or_clear_owner(self):
    self.synchronize()
    self.receive()
    token, csrf = self.pair()
    with self.assertRaises(PhoneError):
      self.api.accept(token, csrf, 'sync', {'schema': 1, 'stream': STREAM, 'sync_sequence': 1, 'phone_send_ns': 11 * NS})
    self.assertIsNotNone(self.api.sample().fix)

  def test_unauthorized_and_wrong_csrf_never_replace_valid_input(self):
    self.synchronize()
    self.receive()
    for token, csrf in (('invalid', self.csrf), (self.token, 'invalid')):
      with self.assertRaises(PhoneError):
        self.api.accept(token, csrf, 'stop', {'schema': 1, 'sync_id': self.sync})
      self.assertIsNotNone(self.api.sample().fix)

  def test_stop_clears_and_late_packet_cannot_revive(self):
    self.synchronize()
    self.receive()
    self.send('stop', {"sync_id": self.sync})
    self.now += 0.1
    self.rejects('fix', self.packet(), 'syncRequired')


class AdapterTests(Fixture, unittest.TestCase):
  def setUp(self):
    fixtures.OfflineTests.setUp(self)
    self.init_live()
    self.provider = fixtures.OfflineTests.provider(self, replace(link(), speed_kph=40.0))
    self.adapter = LiveRoadAdapter(self.api.sample, self.provider, today=lambda: TODAY)
    self.synchronize()

  def tearDown(self):
    fixtures.OfflineTests.tearDown(self)

  def test_live_to_sqlite_to_shared_contract_without_refreshing_repeated_fix(self):
    self.receive(20)
    self.assertIsNone(self.adapter(self.now))
    self.receive(22)
    road = self.adapter(self.now)
    self.assertEqual(RoadInputValidator().validate(road, self.now), '')
    self.now += 0.05
    self.assertIs(self.adapter(self.now), road)
    self.now += 0.1
    self.assertIsNone(self.adapter(self.now))
    self.receive(24)
    self.assertIsNone(self.adapter(self.now))
    self.receive(26)
    self.assertIsNotNone(self.adapter(self.now))

  def test_rejected_and_skipped_records_force_new_road_confirmation(self):
    self.receive(20)
    self.adapter(self.now)
    self.receive(22)
    self.assertIsNotNone(self.adapter(self.now))
    self.now += 0.1
    p = self.packet(24)
    p['mock'] = True
    self.rejects('fix', p, 'untrustedLocation')
    self.assertIsNone(self.adapter(self.now))
    self.receive(26)
    self.assertIsNone(self.adapter(self.now))
    self.receive(28)
    self.assertIsNotNone(self.adapter(self.now))
    self.seq += 1
    self.receive(30)
    self.assertIsNone(self.adapter(self.now))

  def test_poll_after_reauthorization_never_returns_previous_road(self):
    self.receive(20)
    self.adapter(self.now)
    self.receive(22)
    self.assertIsNotNone(self.adapter(self.now))
    self.service.disconnect(self.token)
    self.assertIsNone(self.adapter(self.now))
    self.token, self.csrf = self.pair()
    self.synchronize()
    self.receive(24)
    self.assertIsNone(self.adapter(self.now))
    self.receive(26)
    self.assertIsNotNone(self.adapter(self.now))

  def test_route_recovery_between_fixes_preserves_source_time_and_expiry(self):
    from ..route_hint import RouteHint
    route=[RouteHint('pending','new',reason='rerouting')]
    self.adapter.route=lambda:route[0]
    self.receive(20);self.assertIsNone(self.adapter(self.now))
    self.receive(22);current=self.adapter(self.now)
    self.assertTrue(self.adapter.observation.route_independent)
    self.assertEqual([r.road_id for r in current.context.path],['a'])
    sample=self.api.sample();original=self.provider.previous_fix
    route[0]=RouteHint('active','new',tuple(point(x) for x in range(0,351,50)),self.now+1.)
    self.now+=.03
    road=self.adapter(self.now)
    self.assertIsNotNone(road)
    self.assertEqual(road.context.observed_at,original.observed_at)
    self.assertIs(self.provider.previous_fix,original)
    self.assertEqual(self.api.sample().valid_until_ns,sample.valid_until_ns)
    self.now=sample.valid_until_ns/NS+.001
    self.assertIsNone(self.adapter(self.now))

  def test_route_recovery_does_not_replace_two_raw_matches(self):
    from ..route_hint import RouteHint
    route=[RouteHint('pending','new',reason='rerouting')]
    self.adapter.route=lambda:route[0]
    self.receive(20);self.assertIsNone(self.adapter(self.now))
    route[0]=RouteHint('active','new',tuple(point(x) for x in range(0,351,50)),self.now+1.)
    self.now+=.03;self.assertIsNone(self.adapter(self.now))

  def test_same_route_expiry_recovery_revalidates_without_extending_gps(self):
    from ..route_hint import RouteHint
    route=[RouteHint()];self.adapter.route=lambda:route[0]
    self.receive(20);self.adapter(self.now)
    self.receive(22);self.assertIsNotNone(self.adapter(self.now))
    route[0]=RouteHint('active','same',tuple(point(x) for x in range(0,351,50)),self.now+.02)
    self.assertIsNotNone(self.adapter(self.now))
    self.now+=.03;self.assertIsNotNone(self.adapter(self.now))
    self.assertTrue(self.adapter.observation.route_independent)
    route[0]=replace(route[0],valid_until=self.now+.03)
    self.assertIsNotNone(self.adapter(self.now))


if __name__ == '__main__':
  unittest.main()
