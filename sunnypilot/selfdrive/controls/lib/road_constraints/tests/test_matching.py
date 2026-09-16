"""Synthetic labelled road geometry: matching decisions, never GPS/device accuracy proof."""

import math
import unittest
from dataclasses import replace

from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.contract import RoadInputValidator
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.offline import Link
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.tests import test_offline as fixtures
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.tests.test_offline import fix, link, point


class MatchingTests(unittest.TestCase):
  setUp = fixtures.OfflineTests.setUp
  tearDown = fixtures.OfflineTests.tearDown
  provider = fixtures.OfflineTests.provider
  observe = fixtures.OfflineTests.observe
  warm = fixtures.OfflineTests.warm
  event = fixtures.OfflineTests.event

  def test_stop_retains_only_recent_road_identity_without_heading_or_control(self):
    p = self.provider()
    self.warm(p)
    result = self.observe(p, fix(21.5, 10.2, speed_mps=0.0, bearing_deg=None, bearing_accuracy_deg=None))
    self.assertEqual(result.status, 'lowSpeedHold')
    self.assertEqual(result.link_id, 'a')
    self.assertIsNone(result.road_input)

  def test_stop_cannot_choose_a_road_from_scratch_or_a_single_warmup(self):
    p = self.provider()
    self.assertIsNone(self.observe(p, fix(20, speed_mps=0.0)).link_id)
    self.observe(p, fix(20, 10.1))
    self.assertIsNone(self.observe(p, fix(20, 10.2, speed_mps=0.0)).link_id)

  def test_stop_hold_has_a_fixed_deadline_not_renewed_by_new_fixes(self):
    p = self.provider()
    self.warm(p)
    for i in range(1, 51):
      result = self.observe(p, fix(22, 10.1 + i * 0.1, speed_mps=0.0))
      self.assertEqual(result.status, 'lowSpeedHold')
      self.assertIsNone(result.road_input)
    result = self.observe(p, fix(22, 15.2, speed_mps=0.0))
    self.assertEqual(result.status, 'lowSpeedHoldExpired')
    self.assertIsNone(result.link_id)

  def test_stop_drift_is_bounded_from_original_anchor(self):
    p = self.provider()
    self.warm(p)
    for i in range(1, 12):
      result = self.observe(p, fix(22 + i, 10.1 + i * 0.1, speed_mps=0.5))
    self.assertIsNone(result.link_id)
    self.assertIsNone(result.road_input)

  def test_resume_requires_two_new_moving_samples(self):
    p = self.provider()
    original = self.warm(p).road_input
    self.observe(p, fix(22, 10.2, speed_mps=0.0))
    self.assertEqual(self.observe(p, fix(23, 10.3, speed_mps=3.0)).status, 'warmingUp')
    resumed = self.observe(p, fix(24, 10.4, speed_mps=3.0))
    self.assertEqual(resumed.status, 'derived')
    self.assertGreater(resumed.road_input.context.path_version, original.context.path_version)
    self.assertEqual(RoadInputValidator().validate(resumed.road_input, 10.4), '')

  def test_stale_gap_and_explicit_reset_destroy_stop_anchor(self):
    p = self.provider()
    for action in ('stale', 'gap', 'reset'):
      p.reset('newCase')
      self.warm(p)
      if action == 'stale':
        self.observe(p, fix(22, 10.2, speed_mps=0.0), now=10.5)
      elif action == 'gap':
        self.observe(p, fix(22, 12.0, speed_mps=0.0))
      else:
        p.reset('authorizationEnded')
      self.assertIsNone(self.observe(p, fix(22, 12.1, speed_mps=0.0)).link_id)

  def test_parallel_geometry_overlap_cannot_be_resolved_by_heading_score(self):
    slope = math.tan(math.radians(30))
    skew = replace(link('skew'), points=(point(0, -20 * slope), point(300, 280 * slope)))
    p = self.provider(skew, link('parallel', y=4.0))
    result = self.observe(p, fix(20))
    self.assertEqual(result.status, 'ambiguousRoad')
    self.assertIsNone(result.road_input)

  def test_previous_road_cannot_override_new_parallel_ambiguity(self):
    from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.offline import insert_link

    p = self.provider()
    self.warm(p)
    insert_link(self.db, link('parallel', y=5.0))
    self.db.commit()
    self.assertEqual(self.observe(p, fix(24, 10.2)).status, 'ambiguousRoad')
    self.assertIsNone(self.observe(p, fix(24, 10.3, speed_mps=0.0)).link_id)

  def test_intersecting_road_with_no_height_evidence_is_withheld_near_crossing(self):
    crossing = Link('cross', 's', 'n', '시험 교차로', (point(100, -100), point(100, 100)), 40.0, '2026-09-01')
    p = self.provider(link(), crossing)
    self.warm(p, x=80.0)
    self.assertEqual(self.observe(p, fix(94, 10.7)).status, 'junctionUncertain')
    self.assertIsNone(self.observe(p, fix(100, 11.0)).road_input)
    self.assertEqual(self.observe(p, fix(112, 11.6)).status, 'warmingUp')
    self.assertEqual(self.observe(p, fix(114, 11.7)).status, 'derived')

  def test_fork_does_not_emit_any_branch_event_or_guess_through_endpoint(self):
    straight = link('b', 300, 600, start_node='n1', end_node='n2')
    turn = Link('turn', 'n1', 'north', '회전', (point(300), point(300, 200)), 30.0, '2026-09-01')
    p = self.provider(link(), straight, turn)
    self.event(road='b', at=50)
    before = self.warm(p, x=280.0)
    self.assertEqual([r.road_id for r in before.road_input.context.path], ['a'])
    near = self.observe(p, fix(296, 10.8))
    self.assertIsNone(near.road_input)
    self.assertIsNone(self.observe(p, fix(300, 11.0, speed_mps=0.0)).road_input)
    self.assertEqual(self.observe(p, fix(312, 11.6)).status, 'warmingUp')
    self.assertEqual(self.observe(p, fix(314, 11.7)).link_id, 'b')

  def test_connected_transition_requires_confirmation_on_the_new_link(self):
    p = self.provider(link(), link('b', 300, 600, start_node='n1', end_node='n2'))
    self.warm(p, x=282.0)
    first = self.observe(p, fix(312, 11.1, speed_mps=30.0))
    self.assertEqual(first.status, 'transitionConfirming')
    self.assertIsNone(first.road_input)
    second = self.observe(p, fix(315, 11.2, speed_mps=30.0))
    self.assertEqual(second.status, 'derived')
    self.assertEqual(second.link_id, 'b')

  def test_matching_node_ids_cannot_hide_disconnected_geometry(self):
    p = self.provider(link(), link('b', 320, 600, start_node='n1', end_node='n2'))
    self.warm(p, x=282.0)
    result = self.observe(p, fix(332, 11.1, speed_mps=40.0))
    self.assertEqual(result.status, 'transitionGeometryGap')
    self.assertIsNone(result.road_input)

  def test_distinct_parallel_and_opposing_roads_remain_usable(self):
    p = self.provider(link(), link('parallel', y=25.0), link('opposite', 300, 0, -3, 'r1', 'r0'))
    self.assertEqual(self.warm(p).status, 'derived')

  def test_short_euclidean_jump_cannot_skip_a_long_connected_road(self):
    loop = replace(link(), points=(point(0), point(0, 1000), point(30, 1000), point(30)))
    p = self.provider(loop, link('b', 30, 500, start_node='n1', end_node='n2'))
    self.assertEqual(self.observe(p, fix(0, y=20, bearing_deg=0.0)).status, 'warmingUp')
    self.assertEqual(self.observe(p, fix(0, 10.1, y=22, bearing_deg=0.0)).status, 'derived')
    result = self.observe(p, fix(42, 11.1, speed_mps=50.0))
    self.assertEqual(result.status, 'implausibleTransition')
    self.assertIsNone(result.road_input)

  def test_link_endpoint_projection_is_not_permission_to_drive_past_coverage(self):
    p = self.provider()
    self.warm(p, x=282.0)
    self.assertIsNone(self.observe(p, fix(305, 11.1)).road_input)

  def test_self_crossing_polyline_does_not_hide_ambiguous_progress(self):
    crossed = replace(link(), points=(point(0), point(200), point(200, 100), point(100, 100), point(100, -100)))
    p = self.provider(crossed)
    self.warm(p, x=80.0)
    result = self.observe(p, fix(98, 10.9))
    self.assertEqual(result.status, 'ambiguousRoadGeometry')
    self.assertIsNone(result.road_input)

  def test_same_link_projection_cannot_skip_a_long_hairpin(self):
    loop = replace(link(), points=(point(0), point(0, 1000), point(30, 1000), point(30), point(300)))
    p = self.provider(loop)
    self.assertEqual(self.observe(p, fix(0, y=20, bearing_deg=0.0)).status, 'warmingUp')
    self.assertEqual(self.observe(p, fix(0, 10.1, y=22, bearing_deg=0.0)).status, 'derived')
    result = self.observe(p, fix(42, 11.1, speed_mps=50.0))
    self.assertEqual(result.status, 'implausibleProgress')
    self.assertIsNone(result.road_input)


if __name__ == '__main__':
  unittest.main()
