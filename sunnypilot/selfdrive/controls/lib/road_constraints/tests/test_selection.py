"""Candidate arbitration only; no active vehicle-planner connection."""
from dataclasses import replace
import math
import unittest

from ..selection import RoadCandidateSelector
from .test_road_constraints import make_input


class SelectionTests(unittest.TestCase):
  def setUp(self):
    self.selector = RoadCandidateSelector()
    self.now = 100.

  def step(self, *, missing=False, **changes):
    self.now += .05
    args = dict(now=self.now, valid_until=self.now+.1, v_ego=25., a_ego=0., previous_accel=0.,
      base_accel=0., base_source='e2e', should_stop=False, accel_bounds=(-3.5, 2.),
      action_t=.3, dt=.05, active=True, enabled=True)
    args.update(changes)
    return self.selector.update(None if missing else make_input(now=self.now, sequence=round(self.now*20)), **args)

  def test_disabled_is_exact_base_passthrough(self):
    args = dict(now=100., valid_until=100.1, v_ego=25., a_ego=0., previous_accel=0.,
      base_accel=-.6, base_source='lead0', should_stop=True, accel_bounds=(-3.5, 2.),
      action_t=.3, dt=.05, active=True)
    result = self.selector.update(make_input(), **args)  # enabled omitted
    self.assertFalse(result.selected)
    self.assertEqual((result.acceleration, result.source, result.should_stop), (-.6, 'lead0', True))
    self.assertEqual(result.plan.status, 'disabled')

  def test_only_applied_winner_seeds_release(self):
    self.assertTrue(self.step().selected)
    self.assertFalse(self.step(missing=True).selected)
    self.assertTrue(self.step().selected)
    self.selector.observe_applied(True)
    result = self.step(missing=True, previous_accel=-.5)
    self.assertTrue(result.selected)
    self.assertEqual(result.source, 'roadRelease')
    self.assertEqual(result.plan.event_id, '')
    self.assertAlmostEqual(result.acceleration, -.46)
    # Omitting acknowledgment must not continue a hypothetical release.
    self.assertFalse(self.step(missing=True, previous_accel=-.46).selected)

  def test_stronger_lead_and_e2e_always_win_and_keep_stop(self):
    for source in ('lead0', 'e2e'):
      for stop in (False, True):
        self.assertTrue(self.step().selected)
        self.selector.observe_applied(True)
        result = self.step(base_accel=-4., base_source=source, should_stop=stop, previous_accel=-1.)
        self.assertFalse(result.selected)
        self.assertEqual((result.acceleration, result.source, result.should_stop), (-4., source, stop))
        self.selector.observe_applied(False)

  def test_expired_input_releases_without_old_event_metadata(self):
    self.step(); self.selector.observe_applied(True)
    result = self.step(valid_until=self.now, previous_accel=-.5)
    self.assertEqual(result.plan.rejection, 'inputExpired')
    self.assertEqual(result.plan.event_id, '')
    self.assertEqual(result.source, 'roadRelease')
    for deadline in (0., math.inf, math.nan):
      self.assertFalse(self.step(valid_until=deadline).selected)

  def test_cancel_override_invalid_state_and_disable_drop_release(self):
    for changes in ({'active': False}, {'overridden': True}, {'valid_vehicle': False}, {'enabled': False}):
      self.step(); self.selector.observe_applied(True)
      result = self.step(previous_accel=-1., **changes)
      self.assertFalse(result.selected)
      self.assertEqual(result.acceleration, 0.)
      self.assertFalse(self.step(missing=True, previous_accel=-1.).selected)
    # Fresh navigation cannot reactivate driver-cancelled longitudinal control.
    for _ in range(5):
      self.assertFalse(self.step(active=False).selected)
    self.assertTrue(self.step(active=True).selected)

  def test_gas_release_resumes_from_measured_acceleration(self):
    self.step(overridden=True, previous_accel=-1.)
    result = self.step(a_ego=.5, previous_accel=-1., base_accel=1.)
    self.assertAlmostEqual(result.acceleration, .46)
    self.assertFalse(result.should_stop)

  def test_clock_gap_and_invalid_envelope_preserve_base(self):
    for changes in ({'now': 99.}, {'now': math.nan}, {'now': 200.},
                    {'accel_bounds': (0., -1.)}, {'accel_bounds': (-math.inf, 1.)}):
      self.selector = RoadCandidateSelector()
      self.step(); self.selector.observe_applied(True)
      result = self.step(previous_accel=-1., **changes)
      self.assertFalse(result.selected)
      self.assertEqual(result.acceleration, 0.)

  def test_current_bounds_limit_only_road_candidate(self):
    result = self.step(a_ego=-1., previous_accel=-1., accel_bounds=(-.2, 1.))
    self.assertTrue(result.selected)
    self.assertEqual(result.acceleration, -.2)
    result = self.step(base_accel=-2., accel_bounds=(-.2, 1.))
    self.assertEqual(result.acceleration, -2.)

  def test_coasting_planner_can_supply_an_entirely_negative_envelope(self):
    result = self.step(a_ego=-.5, previous_accel=-.5, base_accel=-.3, accel_bounds=(-3.5, -.3))
    self.assertEqual(result.plan.status, 'constraint')
    self.assertTrue(result.selected)
    self.assertLessEqual(result.acceleration, -.3)

  def test_malformed_road_falls_back_and_clears_selection(self):
    self.step(); self.selector.observe_applied(True)
    bad = replace(make_input(now=self.now+.05), context=None)
    result = self.selector.update(bad, now=self.now+.05, valid_until=self.now+.1,
      v_ego=25., a_ego=0., previous_accel=-1., base_accel=-.7, base_source='lead0', should_stop=True,
      accel_bounds=(-3.5, 2.), action_t=.3, dt=.05, active=True, enabled=True)
    self.assertEqual(result.plan.rejection, 'candidateError')
    self.assertEqual((result.acceleration, result.source, result.should_stop), (-.7, 'lead0', True))
    self.assertFalse(self.step(missing=True).selected)
