from collections import deque
from dataclasses import replace
import math
import unittest

from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.contract import (
  RoadConstraint, RoadContext, RoadInput, RoadInputValidator, RoadKind, RoadLink, RoadSnapshot,
)
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.planner import RoadConstraintPlanner, RoadLimits, advance, braking_distance, clip

LINK = RoadLink("main", "forward")
EVENT = RoadConstraint("camera-1", RoadKind.CAMERA, LINK, 250.0, 250.0, 10.0)
DT = 0.05


def make_input(events=(EVENT,), *, now=100.0, progress=0.0, sequence=1):
  return RoadInput(RoadSnapshot("synthetic", "drive-1", 1, sequence, now, now, 0.0, events),
                   RoadContext("drive-1", 1, (LINK,), progress, now))


def run_scenario(events, *, v_initial=25.0, delay=0.25, intervention=None, max_steps=4000):
  """Independent 20 Hz constant-acceleration plant with an explicit command FIFO.

  Assertions use crossing interpolation, not the planner's braking-distance
  function. This is synthetic longitudinal dynamics, not a C4/vehicle simulation.
  """
  planner = RoadConstraintPlanner()
  previous, a_ego, progress, speed, cruise = 0.0, 0.0, 0.0, v_initial, 0.0
  queued = deque([0.0] * max(1, round(delay / DT)))
  crossings, section_speeds, trace = {}, {}, []
  for frame in range(max_steps):
    now = 100.0 + frame * DT
    sample_time = 100.0 + (frame // 10) * DT * 10
    data = make_input(events, now=sample_time, progress=progress, sequence=frame // 10 + 1)
    data = replace(data, context=replace(data.context, observed_at=now))
    base = clip(v_initial - speed, -1.2, 2.0)
    cruise = clip(base, cruise - 0.8 * DT, cruise + 0.8 * DT)
    base, data, active, overridden = intervention(frame, base, data) if intervention else (cruise, data, True, False)
    plan = planner.update(data, now=now, v_ego=speed, a_ego=a_ego, previous_accel=previous,
                          action_t=delay + DT, dt=DT, active=active, overridden=overridden)
    selected = plan.acceleration is not None and plan.acceleration < base
    output = min(base, plan.acceleration) if plan.acceleration is not None else base
    planner.observe_selection(selected)
    queued.append(output)
    a_ego = queued.popleft()
    next_speed = max(0.0, speed + a_ego * DT)
    next_progress = progress + (speed + next_speed) * DT / 2
    for event in events:
      if event.event_id not in crossings and progress <= event.start_m < next_progress:
        fraction = (event.start_m - progress) / (next_progress - progress)
        crossings[event.event_id] = speed + fraction * (next_speed - speed)
      if event.start_m <= progress <= event.end_m:
        section_speeds.setdefault(event.event_id, []).append(speed)
    trace.append((now, progress, speed, output, plan, selected))
    previous, progress, speed = output, next_progress, next_speed
    if progress > max(event.end_m for event in events) + 80:
      break
  return crossings, section_speeds, trace


class TestRoadContract(unittest.TestCase):
  def test_point_segment_and_free_drive_corridor(self):
    self.assertEqual(RoadInputValidator().validate(make_input(), 100.0), "")
    next_link = RoadLink("next", "east")
    data = make_input((replace(EVENT, link=next_link),))
    data = replace(data, context=replace(data.context, path=(LINK, next_link)))
    self.assertEqual(RoadInputValidator().validate(data, 100.0), "")

  def test_invalid_data_is_rejected_as_a_whole(self):
    mutations = {
      "unknownSourceTime": {"source_at": None}, "sourceStale": {"source_at": 97.0},
      "sourceClock": {"source_at": 101.0}, "receiveStale": {"source_at": 97.5, "received_at": 97.0},
      "receiveClock": {"received_at": math.nan}, "pathMismatch": {"path_version": 2},
      "invalidProgress": {"reference_progress_m": math.inf},
    }
    for expected, changes in mutations.items():
      with self.subTest(expected=expected):
        data = make_input()
        # Check receive age separately with a wider source age.
        validator = RoadInputValidator()
        if expected == "receiveStale":
          validator.limits = replace(validator.limits, source_age=5.0)
        self.assertEqual(validator.validate(replace(data, snapshot=replace(data.snapshot, **changes)), 100.0), expected)

  def test_zero_nan_negative_or_unknown_event_never_becomes_stop(self):
    for event in (replace(EVENT, target_speed=0), replace(EVENT, target_speed=-1),
                  replace(EVENT, target_speed=math.nan), replace(EVENT, start_m=math.inf),
                  replace(EVENT, kind="unknown"), replace(EVENT, end_m=200),
                  replace(EVENT, link=RoadLink("main", "reverse"))):
      with self.subTest(event=event):
        self.assertNotEqual(RoadInputValidator().validate(make_input((event,)), 100.0), "")

  def test_ambiguous_path_stale_position_or_wrong_session_rejected(self):
    for context in (replace(make_input().context, confirmed=False),
                    replace(make_input().context, observed_at=99.0),
                    replace(make_input().context, session="another-drive")):
      self.assertNotEqual(RoadInputValidator().validate(replace(make_input(), context=context), 100.0), "")

  def test_replayed_or_modified_snapshot_cannot_refresh_itself(self):
    validator = RoadInputValidator()
    data = make_input(sequence=2)
    self.assertEqual(validator.validate(data, 100.0), "")
    self.assertEqual(validator.validate(data, 100.1), "")
    self.assertEqual(validator.validate(make_input(sequence=1), 100.1), "snapshotReplay")
    changed = replace(data.snapshot, constraints=(replace(EVENT, target_speed=5),))
    self.assertEqual(validator.validate(replace(data, snapshot=changed), 100.1), "snapshotReplay")
    refreshed_receipt = replace(data.snapshot, sequence=3, received_at=103)
    self.assertEqual(validator.validate(replace(data, snapshot=refreshed_receipt), 103), "sourceStale")

  def test_odometry_must_not_run_backwards(self):
    validator = RoadInputValidator()
    self.assertEqual(validator.validate(make_input(progress=20), 100.0), "")
    self.assertEqual(validator.validate(make_input(progress=19), 100.0), "progressReplay")

  def test_duplicate_ids_and_unbounded_work_are_rejected(self):
    self.assertEqual(RoadInputValidator().validate(make_input((EVENT, EVENT)), 100.0), "invalidEventId")
    events = tuple(replace(EVENT, event_id=str(i)) for i in range(33))
    self.assertEqual(RoadInputValidator().validate(make_input(events), 100.0), "tooManyEvents")


class TestRoadPlanning(unittest.TestCase):
  def plan(self, planner=None, data=None, **kwargs):
    params = {"now": 100.0, "v_ego": 25.0, "a_ego": 0.0, "previous_accel": 0.0, "action_t": 0.3, "dt": DT, "active": True}
    params.update(kwargs)
    return (planner or RoadConstraintPlanner()).update(data or make_input(), **params)

  def test_kinematics_known_constant_acceleration_and_braking(self):
    self.assertEqual(advance(20, -2, 0, 2), (36, 16))
    distance = braking_distance(25, 0, 10, RoadLimits())
    self.assertGreater(distance, (25**2 - 10**2) / 3)  # jerk ramps need more road

  def test_late_event_is_reported_with_bounded_output(self):
    plan = self.plan(data=make_input((replace(EVENT, start_m=3, end_m=3),)))
    self.assertTrue(plan.unreachable)
    self.assertAlmostEqual(plan.acceleration, -0.8 * DT)

  def test_active_segment_decelerates_without_new_stop_request(self):
    event = replace(EVENT, kind=RoadKind.SECTION, start_m=-20, end_m=200)
    plan = self.plan(data=make_input((event,)))
    self.assertLess(plan.acceleration, 0)
    self.assertEqual(plan.event_id, EVENT.event_id)

  def test_invalidated_event_metadata_clears_during_release(self):
    planner = RoadConstraintPlanner()
    planner.observe_selection(True)
    plan = planner.update(None, now=100, v_ego=15, a_ego=-1, previous_accel=-1, action_t=0.3, dt=DT, active=True)
    self.assertEqual(plan.status, "releasing")
    self.assertEqual(plan.event_id, "")
    self.assertEqual(plan.rejection, "noInput")
    self.assertAlmostEqual(plan.acceleration, -1 + 0.8 * DT)

  def test_cancel_and_pedals_clear_release_and_do_not_reenable(self):
    for active, overridden in ((False, False), (True, True)):
      planner = RoadConstraintPlanner()
      planner.observe_selection(True)
      plan = self.plan(planner, active=active, overridden=overridden)
      self.assertIsNone(plan.acceleration)
      self.assertFalse(planner.was_selected)
      # Valid nav recovery cannot bypass an inactive longitudinal state.
      self.assertIsNone(self.plan(planner, active=False).acceleration)
      self.assertIsNotNone(self.plan(planner, active=True).acceleration)

  def test_actual_progress_expires_a_point_without_provider_refresh(self):
    data = make_input(progress=EVENT.end_m + 1)
    self.assertEqual(self.plan(data=data).status, "clear")

  def test_resume_uses_measured_acceleration_after_driver_override(self):
    planner = RoadConstraintPlanner()
    self.plan(planner, overridden=True)
    plan = self.plan(planner, previous_accel=-1.5, a_ego=1.0)
    self.assertAlmostEqual(plan.acceleration, 1.0 - 0.8 * DT)

  def test_vehicle_nonfinite_or_invalid_delay_has_no_candidate(self):
    for changes in ({"v_ego": math.nan}, {"a_ego": math.inf}, {"action_t": 0}, {"dt": -1}, {"v_ego": -1}):
      plan = self.plan(**changes)
      self.assertIsNone(plan.acceleration)
      self.assertEqual(plan.rejection, "invalidVehicleState")

  def test_closed_loop_point_and_segment_targets(self):
    # Preset acceptance: <= 0.5 m/s above target at crossings/inside segments,
    # <= 0.8 m/s^3 command slew when road governs, and no stop at >0 targets.
    for delay in (0.1, 0.25, 0.5):
      events = (EVENT, RoadConstraint("section", RoadKind.SECTION, LINK, 360, 470, 15))
      with self.subTest(delay=delay):
        crossings, section_speeds, trace = run_scenario(events, delay=delay)
        for event in events:
          self.assertIn(event.event_id, crossings)
          self.assertLessEqual(crossings[event.event_id], event.target_speed + 0.5)
          if event.event_id in section_speeds:
            self.assertLessEqual(max(section_speeds[event.event_id]), event.target_speed + 0.5)
        for before, after in zip(trace, trace[1:], strict=False):
          if after[5]:
            self.assertLessEqual(abs(after[3] - before[3]), 0.8 * DT + 1e-8)
        self.assertGreater(min(row[2] for row in trace), 8.0)

  def test_consecutive_constraints_use_strongest_requirement(self):
    events = (replace(EVENT, start_m=180, end_m=180, target_speed=15),
              replace(EVENT, event_id="bump", kind=RoadKind.BUMP, start_m=240, end_m=244, target_speed=5))
    crossings, _, trace = run_scenario(events, v_initial=22)
    for event in events:
      self.assertLessEqual(crossings[event.event_id], event.target_speed + 0.5)
    self.assertIn("bump", {row[4].event_id for row in trace if row[5]})

  def test_binding_event_is_independent_of_input_order_during_slew(self):
    gentle = replace(EVENT, event_id="gentle", start_m=350, end_m=350, target_speed=20)
    severe = replace(EVENT, event_id="severe", start_m=80, end_m=80, target_speed=5)
    for events in ((gentle, severe), (severe, gentle)):
      self.assertEqual(self.plan(data=make_input(events)).event_id, "severe")


if __name__ == "__main__":
  unittest.main()
