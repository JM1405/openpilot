import json
import math
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.contract import RoadInputValidator, RoadKind
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.offline import (
  EARTH_M,
  Fix,
  Link,
  OfflineProvider,
  RoadStore,
  create_schema,
  insert_link,
  project,
)
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.planner import RoadConstraintPlanner

TODAY = date(2026, 9, 15)
ORIGIN = (127.4, 35.8)


def point(x, y=0.):
  return (ORIGIN[0] + math.degrees(x / (EARTH_M * math.cos(math.radians(ORIGIN[1])))),
          ORIGIN[1] + math.degrees(y / EARTH_M))


def link(link_id="a", x=0., end=300., y=0., start_node="n0", end_node="n1", **kwargs):
  return Link(link_id, start_node, end_node, "시험로", (point(x, y), point(end, y)), 80., "2026-09-01", **kwargs)


def fix(x, now=10., y=0., **kwargs):
  return replace(Fix(*point(x, y), 90., 20., 2., 5., now), **kwargs)


class OfflineTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.path = Path(self.tmp.name) / "test.sqlite"
    self.db = sqlite3.connect(self.path)
    create_schema(self.db)
    self.db.execute("INSERT INTO metadata VALUES('dataset_id','synthetic-test')")
    self.stores = []

  def tearDown(self):
    for store in self.stores:
      store.close()
    self.db.close()
    self.tmp.cleanup()

  def provider(self, *roads):
    for road in roads or (link(),):
      insert_link(self.db, road)
    self.db.commit()
    store = RoadStore(self.path)
    self.stores.append(store)
    from .event_fixtures import bind_fixture
    for event in store.db.execute('SELECT * FROM events WHERE verified=1'):
      row = store.db.execute('SELECT * FROM links WHERE id=?', (event['link_id'],)).fetchone()
      if row is not None and event['target_kph'] is not None:
        try:
          bound = bind_fixture(dict(event), store.link(row), store)
        except ValueError:  # Deliberately malformed event fixture remains unreviewed.
          continue
        self.db.execute('UPDATE events SET attributes=? WHERE id=?', (bound['attributes'], event['id']))
    self.db.commit()
    return OfflineProvider(store)

  def observe(self, provider, sample, **kwargs):
    return provider.observe(sample, now=kwargs.get("now", sample.observed_at), today=TODAY)

  def warm(self, provider, x=20.):
    self.assertEqual(self.observe(provider, fix(x)).status, "warmingUp")
    return self.observe(provider, fix(x + 2., 10.1))

  def event(self, event_id="test-camera", at=150., verified=1, target=36., updated="2026-09-01", kind="camera", road="a"):
    source = 'data.go.kr/15028200' if kind == 'camera' else 'data.go.kr/15160269'
    attrs = {'enforcement_code': '01', 'direction_code': '03'} if kind == 'camera' else {'shape': '원호형'}
    self.db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?)",
      (event_id, kind, *point(at), target, updated, source, json.dumps(attrs), road, at, verified))
    self.db.commit()

  def test_distance_and_direction_are_not_straight_line_to_an_event(self):
    gap, along, course = project(point(100, 50), (point(0), point(100), point(100, 100)))
    self.assertAlmostEqual(gap, 0., places=6)
    self.assertAlmostEqual(along, 150., places=4)
    self.assertAlmostEqual(course, 0., places=5)

  def test_derived_snapshot_passes_shared_contract(self):
    p = self.provider()
    result = self.warm(p)
    self.assertEqual(result.status, "derived")
    self.assertEqual(RoadInputValidator().validate(result.road_input, 10.1), "")
    self.assertAlmostEqual(result.road_input.snapshot.constraints[0].target_speed, 80 / 3.6)
    self.assertEqual(result.road_input.snapshot.source_at, 10.1)

  def test_opposing_lane_selected_by_heading(self):
    reverse = link("opposite", 300., 0., 3., "r1", "r0")
    p = self.provider(link(), reverse)
    self.assertEqual(self.warm(p).link_id, "a")

  def test_parallel_road_ambiguity_clears_input(self):
    p = self.provider(link(), link("parallel", y=5.))
    result = self.observe(p, fix(30, y=2.5))
    self.assertEqual(result.status, "ambiguousRoad")
    self.assertIsNone(result.road_input)

  def test_stacked_roads_are_not_resolved_by_gps_alone(self):
    p = self.provider(link(), link("bridge"))
    self.assertEqual(self.observe(p, fix(30)).status, "ambiguousRoad")

  def test_first_sample_does_not_confirm_a_path(self):
    self.assertIsNone(self.observe(self.provider(), fix(30)).road_input)

  def test_quality_age_and_nonfinite_fixes(self):
    p = self.provider()
    cases = [(replace(fix(20), accuracy_m=16.), "uncertainFix"),
             (replace(fix(20), bearing_accuracy_deg=30.), "uncertainFix"),
             (replace(fix(20), speed_mps=0.), "headingUnavailableAtLowSpeed"),
             (replace(fix(20), lon=math.nan), "invalidFix"),
             (replace(fix(20), observed_at=9.), "staleFix")]
    for sample, status in cases:
      with self.subTest(status=status):
        self.assertEqual(self.observe(p, sample, now=10.).status, status)

  def test_jump_replay_backwards_and_gap(self):
    for sample, status in [(fix(200, 10.2), "positionJump"), (fix(22, 10.1), "fixReplay"),
                           (fix(21, 10.2), "backwardsProgress"), (fix(25, 12.), "warmingUp")]:
      with self.subTest(status=status):
        p = OfflineProvider(self.provider().store) if not self.stores else OfflineProvider(self.stores[0])
        self.warm(p)
        self.assertEqual(self.observe(p, sample).status, status)

  def test_unused_restricted_and_old_roads(self):
    for change in ({"road_use": "1"}, {"rest_veh": "15"}, {"updated": "2020-01-01"}):
      p = self.provider(replace(link(), **change))
      self.assertEqual(self.observe(p, fix(20)).status, "unusableOrOldRoad")
      self.db.execute("DELETE FROM bounds")
      self.db.execute("DELETE FROM links")
      self.db.commit()

  def test_unique_successor_and_fork(self):
    nxt = link("b", 300., 600., start_node="n1", end_node="n2")
    p = self.provider(link(), replace(nxt, speed_kph=40.))
    result = self.warm(p)
    self.assertEqual([r.road_id for r in result.road_input.context.path], ["a", "b"])
    change = result.road_input.snapshot.constraints[1]
    self.assertAlmostEqual(change.start_m, 278., places=4)
    self.assertAlmostEqual(change.target_speed, 40 / 3.6)
    insert_link(self.db, link("exit", 300., 500., y=15., start_node="n1", end_node="exit-node"))
    self.db.commit()
    result = self.observe(p, fix(24., 10.2))
    self.assertEqual(result.horizon_end, "fork")
    self.assertEqual([r.road_id for r in result.road_input.context.path], ["a"])
    self.assertEqual(RoadInputValidator().validate(result.road_input, 10.2), "")

  def test_geometry_gap_stops_horizon(self):
    p = self.provider(link(), link("gap", 350., 500., start_node="n1", end_node="n2"))
    self.assertEqual(self.warm(p).horizon_end, "geometryGap")

  def test_loop_stops_horizon(self):
    p = self.provider(link(start_node="same", end_node="same"))
    self.assertEqual(self.warm(p).horizon_end, "loop")

  def test_long_link_has_bounded_relative_constraint_distances(self):
    result = self.warm(self.provider(link(end=20000.)), x=15000.)
    self.assertEqual(RoadInputValidator().validate(result.road_input, 10.1), "")

  def test_wrong_road_and_unverified_events_do_not_reach_control(self):
    self.event(verified=0)
    self.event(event_id="other-road", road="elsewhere")
    p = self.provider()
    result = self.warm(p)
    self.assertEqual(result.unverified_events, 1)
    self.assertFalse(any(e.kind == RoadKind.CAMERA for e in result.road_input.snapshot.constraints))

  def test_passed_event_removed_and_old_event_ignored(self):
    self.event(at=22.5)
    self.event(event_id="old", at=30., updated="2020-01-01")
    p = self.provider()
    result = self.warm(p)
    self.assertEqual([e.event_id for e in result.road_input.snapshot.constraints if e.kind == RoadKind.CAMERA], ["test-camera"])
    result = self.observe(p, fix(24., 10.2))
    self.assertFalse(any(e.kind == RoadKind.CAMERA for e in result.road_input.snapshot.constraints))

  def test_ramp_limit_is_withheld_not_treated_as_virtual_geometry(self):
    result = self.warm(self.provider(link(connector="1")))
    self.assertEqual(result.status, "derived")
    self.assertEqual(result.road_input.snapshot.constraints, ())

  def test_bump_requires_a_target_and_verified_binding(self):
    self.event(kind="bump", target=None)
    result = self.warm(self.provider())
    self.assertFalse(any(e.kind == RoadKind.BUMP for e in result.road_input.snapshot.constraints))

  def test_public_camera_needs_semantics_and_target_direction_evidence(self):
    self.event(at=100.)
    self.db.execute("UPDATE events SET source='data.go.kr/15028200'")
    p = self.provider()
    for status in ("noSpeedEnforcement", "sectionNeedsPair", "invalidSection", "pointCandidate"):
      attributes = {"semantic": {"status": status}}
      self.db.execute("UPDATE events SET attributes=?", (json.dumps(attributes),))
      self.db.commit()
      p.reset("test")
      self.assertFalse(any(e.kind == RoadKind.CAMERA for e in self.warm(p).road_input.snapshot.constraints))
    attributes.update(enforcement_direction_verified=True, target_road_position_verified=True)
    self.db.execute("UPDATE events SET attributes=?", (json.dumps(attributes),))
    self.db.commit()
    p.reset("test")
    # Legacy booleans no longer replace a bound evidence review.
    self.assertFalse(any(e.kind == RoadKind.CAMERA for e in self.warm(p).road_input.snapshot.constraints))

  def test_corrupt_public_event_metadata_does_not_crash_or_emit(self):
    self.event(at=100.)
    self.db.execute("UPDATE events SET source='data.go.kr/15028200', attributes='null'")
    p = self.provider()
    self.assertFalse(any(e.kind == RoadKind.CAMERA for e in self.warm(p).road_input.snapshot.constraints))

  def test_actual_shared_planner_consumes_offline_camera(self):
    self.event(at=150.)
    result = self.warm(self.provider(replace(link(), speed_kph=120.)))
    planner = RoadConstraintPlanner()
    plan = planner.update(result.road_input, now=10.1, v_ego=25., a_ego=0., previous_accel=0.,
                          action_t=.25, dt=.05, active=True)
    self.assertEqual(plan.event_id, "test-camera")
    self.assertLess(plan.acceleration, 0.)
    stopped = planner.update(None, now=10.2, v_ego=25., a_ego=0., previous_accel=plan.acceleration,
                             action_t=.25, dt=.05, active=True, overridden=True)
    self.assertEqual(stopped.status, "overridden")


if __name__ == "__main__":
  unittest.main()
