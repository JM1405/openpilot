"""Synthetic motion truth only. No vehicle feed, live clock mapping or actuation."""
import math
import unittest
from dataclasses import replace

from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.motion import MotionSample, MotionTracker
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.motion_shadow import MotionRoadObserver
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.offline import distance, insert_link
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.tests import test_offline as fixtures
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.tests.test_offline import fix, link, point


def gps(t, x=None, **kwargs):
  return fix(20+(t-10)*10 if x is None else x, t, speed_mps=10., accuracy_m=2., bearing_accuracy_deg=2., **kwargs)


def advance(tracker, start, end, speed=10., yaw=0.):
  for i in range(round((end-start)*100)+1):
    t=round(start+i*.01, 8)
    tracker.push_motion(MotionSample(t, speed, yaw), now=t)


def warm():
  t=MotionTracker()
  advance(t, 9.98, 10.03)
  assert t.accept_fix(gps(10), now=10.03)
  advance(t, 10.04, 11.03)
  assert t.accept_fix(gps(11), now=11.03)
  return t


class MotionTests(unittest.TestCase):
  def test_one_hz_anchor_does_not_change_its_time(self):
    t=warm()
    advance(t,11.04,11.99)
    result=t.estimate(11.99)
    self.assertTrue(result.observation_only)
    self.assertEqual(result.anchor_at,11.)
    self.assertEqual(result.estimated_at,11.99)
    self.assertLess(distance((result.lon,result.lat),point(39.9)), .001)
    self.assertGreater(result.error_radius_m,2.)
    self.assertIsNone(t.estimate(12.26))
    self.assertEqual(t.status,'anchorExpired')

  def test_polling_does_not_refresh_motion_or_gps_clocks(self):
    t=warm()
    a=t.estimate(11.03); b=t.estimate(11.13)
    self.assertEqual(a,b)
    self.assertIsNone(t.estimate(11.19))
    self.assertEqual(t.status,'motionExpired')

  def test_one_gps_cannot_be_confirmed_by_many_motion_samples(self):
    t=MotionTracker();advance(t,9.98,10.03)
    t.accept_fix(gps(10),now=10.03)
    advance(t,10.04,10.99)
    self.assertIsNone(t.estimate(10.99))
    self.assertEqual(t.status,'warmingUp')

  def test_jittered_one_hz_independent_fixes_confirm(self):
    t=MotionTracker();advance(t,9.98,10.03)
    t.accept_fix(gps(10),now=10.03)
    advance(t,10.04,11.04)
    self.assertTrue(t.accept_fix(gps(11.001),now=11.04))
    self.assertIsNotNone(t.estimate(11.04))

  def test_braking_uses_new_vehicle_speeds(self):
    t=warm()
    for i in range(104,201):
      at=10+i*.01
      t.push_motion(MotionSample(at,10-2*(at-11.03),0),now=at)
    result=t.estimate(12.)
    # 0.03 s at 10 m/s, then 0.97 s with a=-2 m/s^2.
    self.assertLess(distance((result.lon,result.lat),point(30+.3+9.7-.97**2)), .001)

  def test_turn_integration_tracks_analytic_circle(self):
    t=warm(); start=11.03
    # Start turning after the already supplied straight samples.
    for i in range(1,81):
      at=start+i*.01
      t.push_motion(MotionSample(at,10,.2),now=at)
    e=t.estimate(start+.8)
    # First interval's yaw ramps from 0 to .2; compare with exact circle allowing ramp.
    x=30.3+50*math.sin(.16); y=-50*(1-math.cos(.16))
    self.assertLess(distance((e.lon,e.lat),point(x,y)), .02)
    self.assertAlmostEqual(e.bearing_deg,90+math.degrees(.159),places=7)

  def test_motion_gap_needs_two_new_gps(self):
    t=warm();t.push_motion(MotionSample(11.3,10,0),now=11.3)
    self.assertIsNone(t.estimate(11.3))
    self.assertTrue(t.accept_fix(gps(11.3),now=11.3))
    self.assertFalse(t.confirmed)

  def test_fix_replay_and_position_heading_speed_disagreement_revoke(self):
    cases=[(gps(11),'fixReplay'),(gps(11.1,x=100),'gpsMotionPositionMismatch'),
           (replace(gps(11.1),bearing_deg=180),'gpsMotionHeadingMismatch'),
           (replace(gps(11.1),speed_mps=20),'gpsVehicleSpeedMismatch')]
    for candidate,status in cases:
      with self.subTest(status=status):
        t=warm();advance(t,11.04,11.13)
        self.assertFalse(t.accept_fix(candidate,now=11.13))
        self.assertEqual(t.status,status);self.assertIsNone(t.estimate(11.13))

  def test_stale_future_poor_accuracy_and_low_speed_rejected(self):
    for candidate in (gps(10.5),gps(12),replace(gps(11.1),accuracy_m=45),replace(gps(11.1),speed_mps=0)):
      t=warm();advance(t,11.04,11.13)
      self.assertFalse(t.accept_fix(candidate,now=11.13))
      self.assertIsNone(t.estimate(11.13))

  def test_uncertainty_counts_against_original_fix_freshness(self):
    t=warm();advance(t,11.04,11.29)
    self.assertFalse(t.accept_fix(gps(11.1),now=11.29,clock_uncertainty_s=.02))
    self.assertEqual(t.status,'staleOrUncertainFix')

  def test_uncertainty_and_bad_heading_grow_until_budget_exhausted(self):
    t=warm();advance(t,11.04,11.13)
    self.assertTrue(t.accept_fix(replace(gps(11.1),accuracy_m=14,bearing_accuracy_deg=20),now=11.13))
    advance(t,11.14,11.5)
    self.assertIsNone(t.estimate(11.5))
    self.assertEqual(t.status,'motionBudgetExceeded')

  def test_invalid_motion_and_clock_revoke(self):
    cases=[MotionSample(11.04,10,0,False),MotionSample(11.04,float('nan'),0),
           MotionSample(11.04,10,float('inf')),MotionSample(11.04,50,0),MotionSample(11.03,10,0)]
    for s in cases:
      t=warm();self.assertFalse(t.push_motion(s,now=11.04));self.assertIsNone(t.estimate(11.04))
    t=warm();self.assertIsNone(t.estimate(10.9));self.assertEqual(t.status,'clockJump')

  def test_revoke_cannot_reuse_old_motion_or_gps(self):
    t=warm();t.revoke('authorizationEnded')
    self.assertFalse(t.push_motion(MotionSample(11.03,10,0),now=11.04))
    self.assertFalse(t.accept_fix(gps(11),now=11.04))
    self.assertIsNone(t.estimate(11.04))

  def test_expired_anchor_needs_two_new_independent_fixes(self):
    t=warm();advance(t,11.04,12.4)
    self.assertIsNone(t.estimate(12.4))
    self.assertTrue(t.accept_fix(gps(12.4),now=12.4))
    self.assertFalse(t.confirmed)
    advance(t,12.41,13.4)
    self.assertTrue(t.accept_fix(gps(13.4),now=13.4))
    self.assertIsNotNone(t.estimate(13.4))

  def test_stale_negative_and_future_motion_cannot_seed_history(self):
    for sample,now in ((MotionSample(-.01,10,0),0.),(MotionSample(9.,10,0),10.),
                       (MotionSample(10.1,10,0),10.)):
      t=MotionTracker()
      self.assertFalse(t.push_motion(sample,now=now))
      self.assertFalse(t.history)

  def test_anchor_clock_error_is_kept_and_not_renewed_on_poll(self):
    t=warm();advance(t,11.04,11.13)
    self.assertTrue(t.accept_fix(gps(11.1),now=11.13,clock_uncertainty_s=.02))
    e=t.estimate(11.13)
    self.assertEqual(e.anchor_clock_uncertainty_s,.02)
    self.assertGreater(e.error_radius_m,2.2)
    advance(t,11.14,12.34)
    self.assertIsNone(t.estimate(12.34))
    self.assertEqual(t.status,'anchorExpired')

  def test_unbracketed_fix_never_backfills_vehicle_motion(self):
    t=MotionTracker();advance(t,10.01,10.03)
    self.assertFalse(t.accept_fix(gps(10),now=10.03))
    self.assertEqual(t.status,'missingMotionHistory')


class ShadowRoadTests(unittest.TestCase):
  setUp=fixtures.OfflineTests.setUp
  tearDown=fixtures.OfflineTests.tearDown
  provider=fixtures.OfflineTests.provider

  def observer(self,*links):
    p=self.provider(*links)
    return MotionRoadObserver(p.store,today=fixtures.TODAY)

  def prepare(self,o,x=20):
    advance(o,9.98,10.03)
    o.accept_fix(gps(10,x=x),now=10.03)
    # Polling between fixes must not destroy raw-road warmup.
    for i in range(104,204):
      at=round(9+i*.01,8)
      o.push_motion(MotionSample(at,10,0),now=at)
      o.sample(at)
    o.accept_fix(gps(11.001,x=x+10.01),now=11.03)
    return o.sample(11.03)

  def test_one_hz_road_observation_never_returns_control_input(self):
    o=self.observer();result=self.prepare(o)
    self.assertEqual(result.status,'shadowPosition')
    self.assertEqual(result.link_id,'a')
    self.assertFalse(hasattr(result,'road_input'))
    self.assertFalse(hasattr(result,'target_speed'))
    advance(o,11.04,11.99)
    result=o.sample(11.99)
    self.assertAlmostEqual(result.progress_m,39.9,places=3)
    self.assertEqual(result.estimate.anchor_at,11.001)

  def test_parallel_road_stays_ambiguous(self):
    o=self.observer(link(),link('parallel',y=4))
    self.assertIsNone(self.prepare(o).estimate)

  def test_uncertainty_reaching_another_road_revokes(self):
    o=self.observer();self.prepare(o)
    insert_link(self.db,link('parallel',y=8));self.db.commit()
    advance(o,11.04,11.99)
    self.assertEqual(o.sample(11.99).status,'estimatedRoadAmbiguous')
    self.assertIsNone(o.sample(12).estimate)

  def test_prediction_cannot_cross_a_link_boundary(self):
    o=self.observer();self.assertEqual(self.prepare(o,x=270).status,'shadowPosition')
    advance(o,11.04,12.2)
    result=o.sample(12.2)
    self.assertEqual(result.status,'estimatedRoadBoundary')
    self.assertIsNone(result.estimate)

  def test_route_change_rebuilds_only_current_road(self):
    from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.route_hint import RouteHint
    o=self.observer();self.prepare(o)
    o.set_route(None)
    o.set_route(RouteHint('pending',reason='rerouting'))
    self.assertEqual(o.sample(11.04).status,'currentRoadOnly')
    self.assertEqual([r.road_id for r in o.anchor_road.context.path],['a'])

  def test_active_route_expiry_rebuilds_current_road_without_new_gps(self):
    from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.route_hint import RouteHint
    o=self.observer()
    o.set_route(RouteHint('active','synthetic-route',tuple(point(x) for x in range(0,351,50)),11.2))
    self.assertEqual(self.prepare(o).status,'shadowPosition')
    advance(o,11.04,11.2)
    self.assertEqual(o.sample(11.2).status,'currentRoadOnly')
    self.assertEqual([r.road_id for r in o.anchor_road.context.path],['a'])

  def test_expired_route_recovery_preserves_motion_but_rebuilds_road(self):
    from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.route_hint import RouteHint
    o=self.observer()
    route=RouteHint('active','same',tuple(point(x) for x in range(0,351,50)),11.2)
    o.set_route(route);self.prepare(o)
    original=o.tracker.anchor
    advance(o,11.04,11.3)
    self.assertEqual(o.sample(11.3).status,'currentRoadOnly')
    self.assertIs(o.tracker.anchor,original)
    o.set_route(replace(route,valid_until=11.5))
    self.assertIsNotNone(o.sample(11.3).estimate)
    self.assertEqual(o.sample(11.3).estimate.anchor_at,11.001)

  def test_route_recovery_cannot_override_estimated_road_ambiguity(self):
    from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.route_hint import RouteHint
    o=self.observer();self.prepare(o)
    o.set_route(RouteHint('pending',reason='rerouting'))
    insert_link(self.db,link('parallel',y=8));self.db.commit()
    advance(o,11.04,11.99);self.assertIsNone(o.sample(11.99).estimate)
    o.set_route(None)
    self.assertEqual(o.sample(11.99).status,'estimatedRoadAmbiguous')
    self.assertIsNone(o.anchor_road)

  def test_raw_road_confirmation_never_uses_estimates(self):
    o=self.observer();advance(o,9.98,10.03)
    o.accept_fix(gps(10),now=10.03)
    for i in range(104,200):
      at=round(9+i*.01,8)
      o.push_motion(MotionSample(at,10,0),now=at)
      self.assertIsNone(o.sample(at).estimate)
    self.assertEqual(o.provider.previous_fix.observed_at,10.)
    self.assertEqual(o.provider.sequence,0)

  def test_cadence_option_is_bounded_and_default_unchanged(self):
    from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.offline import OfflineProvider
    p=self.provider()
    self.assertEqual(p.max_fix_interval_s,1.)
    for bad in (True,0,1.251,float('nan')):
      with self.assertRaises(ValueError):OfflineProvider(p.store,max_fix_interval_s=bad)
