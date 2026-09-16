import math
import unittest
from dataclasses import replace

from . import test_offline as fixtures
from .test_offline import point, link, fix
from ..contract import RoadKind, RoadInputValidator
from ..curves import analyze, curvature, LIMITS
from ..offline import insert_link
from ..planner import RoadConstraintPlanner


def bend_points(radius=80., degrees=70., step=5., lead=120., tail=140., sign=1.):
  """Analytic straight/circle/tangent geometry, no GPS or real road claims."""
  count = max(1, math.ceil(lead/step))
  points = [(-lead + lead*i/count, 0.) for i in range(count+1)]
  angle = math.radians(degrees)
  count = math.ceil(radius*angle/step)
  points.extend((radius*math.sin(angle*i/count), sign*radius*(1-math.cos(angle*i/count))) for i in range(1, count+1))
  x, y = points[-1]
  count = max(1, math.ceil(tail/step))
  points.extend((x + tail*i/count*math.cos(angle), y + sign*tail*i/count*math.sin(angle)) for i in range(1, count+1))
  return tuple(point(x+lead, y) for x, y in points)


def curved_link(road_id='a', **kwargs):
  return replace(link(road_id), points=bend_points(**kwargs))


class CurveGeometryTests(unittest.TestCase):
  def test_inverse_circumradius_and_straight(self):
    self.assertAlmostEqual(curvature((10., 0.), (0., 10.), (-10., 0.)), .1)
    self.assertEqual(curvature((0., 0.), (10., 0.), (20., 0.)), 0.)

  def test_known_radius_speed_and_conservative_extent(self):
    result = analyze(bend_points())
    self.assertEqual(result.rejections, ())
    self.assertEqual(len(result.bends), 1)
    bend = result.bends[0]
    self.assertAlmostEqual(1/bend.curvature, 80., delta=2.)
    self.assertAlmostEqual(bend.target_speed, math.sqrt(1.5*80), delta=.2)
    self.assertLessEqual(bend.start_m, 120.)
    self.assertGreaterEqual(bend.end_m, 120.+80*math.radians(70.))
    short = analyze(bend_points(radius=30., degrees=30., step=1.)).bends[0]
    self.assertLessEqual(short.target_speed, math.sqrt(1.5*30.)*1.01)

  def test_mirror_and_reverse_keep_target_and_change_turn_sign(self):
    base = analyze(bend_points()).bends[0]
    for points in (bend_points(sign=-1), tuple(reversed(bend_points()))):
      bend = analyze(points).bends[0]
      self.assertLess(bend.curvature, 0.)
      self.assertAlmostEqual(bend.target_speed, base.target_speed, delta=.2)

  def test_sampling_density_does_not_invent_a_different_radius(self):
    speeds = [analyze(bend_points(step=step)).bends[0].target_speed for step in (1., 2.5, 5., 10.)]
    self.assertLess(max(speeds)-min(speeds), .5)
    # Dense vertices on a gentle curve must not all fall below an angular cutoff.
    gentle = [analyze(bend_points(radius=600., step=step)).bends[0].target_speed for step in (1., 5.)]
    self.assertLess(abs(gentle[0]-gentle[1]), .5)

  def test_straight_and_small_coordinate_noise_do_not_create_curve(self):
    for noise in (0., .03, .2):
      points = tuple(point(i*5, noise*(-1)**i) for i in range(100))
      self.assertEqual(analyze(points).bends, ())

  def test_isolated_kink_is_not_a_curve(self):
    points = tuple(point(x) for x in range(0, 125, 5)) + tuple(point(120, y) for y in range(5, 150, 5))
    result = analyze(points)
    self.assertFalse(result.bends)
    self.assertIn('sharpVertex', result.rejections)

  def test_sparse_arc_cannot_be_repaired_by_resampling(self):
    result = analyze(bend_points(radius=150., step=35.))
    self.assertFalse(result.bends)
    self.assertIn('sparseGeometry', result.rejections)

  def test_large_single_gap_inside_curve_withholds_it(self):
    points = list(bend_points(radius=150.))
    del points[30:38]
    self.assertFalse(analyze(tuple(points)).bends)

  def test_geometry_boundary_is_not_guessed_through(self):
    for kwargs in ({'lead': 10.}, {'tail': 10.}):
      result = analyze(bend_points(**kwargs))
      self.assertFalse(result.bends)
      self.assertIn('linkBoundary', result.rejections)

  def test_self_intersection_and_overlapping_return_are_rejected(self):
    for points in (((0,0),(100,100),(0,100),(100,0)), ((0,0),(100,0),(50,0),(150,0))):
      result = analyze(tuple(point(x,y) for x,y in points))
      self.assertFalse(result.bends)
      self.assertIn('selfIntersection', result.rejections)

  def test_invalid_and_duplicate_coordinates(self):
    valid = bend_points()
    for bad in (float('nan'), float('inf'), 200., True):
      result = analyze(((bad, 35.8),)+valid[1:])
      self.assertEqual(result.rejections, ('invalidCoordinates',))
    self.assertEqual(analyze(valid[:4]+valid[3:]).rejections, ('duplicatePoints',))

  def test_tiny_radius_is_withheld_instead_of_speed_clamped_up(self):
    result = analyze(bend_points(radius=15., degrees=100., step=1.))
    self.assertFalse(result.bends)
    self.assertIn('radiusTooSmall', result.rejections)

  def test_bounded_work_for_excessive_geometry(self):
    self.assertEqual(analyze(tuple(point(i) for i in range(LIMITS.max_points+1))).rejections, ('tooManyPoints',))
    self.assertEqual(analyze((point(0),point(6000),point(12000))).rejections, ('geometryTooLong',))

  def test_s_bend_keeps_two_opposing_segments(self):
    first = bend_points(tail=100.)
    # Use two independently bounded mirrored bends in one continuous directed link.
    # Rotate the second start/tangent to match the first outgoing bearing.
    from ..offline import xy
    second = bend_points(sign=-1.)
    angle = math.radians(70.)
    origin = first[-1]
    from ..offline import EARTH_M
    translated = []
    for p in second[1:]:
      x,y = xy(*p,second[0]); x,y = x*math.cos(angle)-y*math.sin(angle), x*math.sin(angle)+y*math.cos(angle)
      translated.append((origin[0]+math.degrees(x/(EARTH_M*math.cos(math.radians(origin[1])))),origin[1]+math.degrees(y/EARTH_M)))
    result = analyze(first+tuple(translated))
    self.assertEqual(len(result.bends), 2)
    self.assertLess(result.bends[0].curvature*result.bends[1].curvature,0.)


class CurveProviderTests(unittest.TestCase):
  setUp = fixtures.OfflineTests.setUp
  tearDown = fixtures.OfflineTests.tearDown
  provider = fixtures.OfflineTests.provider
  observe = fixtures.OfflineTests.observe
  warm = fixtures.OfflineTests.warm
  event = fixtures.OfflineTests.event

  def curves(self, observation):
    return [e for e in observation.road_input.snapshot.constraints if e.kind == RoadKind.CURVE] if observation.road_input else []

  def test_candidate_uses_directed_distance_stable_id_and_existing_planner(self):
    provider = self.provider(curved_link())
    result = self.warm(provider)
    curve = self.curves(result)[0]
    self.assertEqual(result.curve_candidates,1)
    self.assertEqual(RoadInputValidator().validate(result.road_input,10.1),'')
    self.assertEqual(curve.link,curved_link().ref)
    next_result = self.observe(provider,fix(24,10.2))
    newer = self.curves(next_result)[0]
    self.assertEqual(curve.event_id,newer.event_id)
    self.assertAlmostEqual(curve.start_m-newer.start_m,2.,delta=.01)
    plan = RoadConstraintPlanner().update(result.road_input,now=10.1,v_ego=20.,a_ego=0.,previous_accel=0.,action_t=.25,dt=.05,active=True)
    self.assertEqual(plan.kind,'curve')
    self.assertLess(plan.acceleration,0.)

  def test_unique_successor_curve_but_no_fork_prediction(self):
    road = replace(curved_link('b'), start='n1',end='n2',points=tuple(point(300+x, y) for x,y in self.metric_bend()))
    provider = self.provider(link(),road)
    self.assertTrue(self.curves(self.warm(provider)))
    insert_link(self.db,link('ramp',300.,450.,start_node='n1',end_node='n3',connector='1'))
    self.db.commit()
    result = self.observe(provider,fix(24,10.2))
    self.assertEqual(result.horizon_end,'fork')
    self.assertFalse(self.curves(result))

  @staticmethod
  def metric_bend():
    from ..offline import xy
    points=bend_points()
    return [xy(*p,points[0]) for p in points]

  def test_join_kink_never_becomes_map_curve(self):
    following=replace(link('b',start_node='n1',end_node='n2'),points=(point(300),point(350,200)))
    result=self.warm(self.provider(link(),following))
    self.assertFalse(self.curves(result))
    self.assertEqual(result.horizon_end,'unconfirmedTurn')

  def test_parallel_match_stale_and_low_speed_clear_curve(self):
    provider=self.provider(curved_link())
    self.assertTrue(self.curves(self.warm(provider)))
    self.assertFalse(self.curves(self.observe(provider,fix(24,10.2),now=10.5)))
    provider.reset('test')
    self.warm(provider)
    self.assertFalse(self.curves(self.observe(provider,fix(24,10.2,speed_mps=0.,bearing_deg=None,bearing_accuracy_deg=None))))
    insert_link(self.db,link('parallel',y=4.));self.db.commit()
    self.assertEqual(self.observe(provider,fix(26,10.3)).status,'ambiguousRoad')

  def test_reverse_direction_does_not_receive_forward_link_curve(self):
    result=self.observe(self.provider(curved_link()),fix(30,bearing_deg=270.))
    self.assertFalse(self.curves(result))
    self.assertEqual(result.status,'noRoadMatch')

  def test_ramp_and_old_map_do_not_create_curve(self):
    provider=self.provider(replace(curved_link(),connector='1'))
    result=self.warm(provider)
    self.assertFalse(self.curves(result));self.assertIn('rampUnconfirmed',result.curve_rejections)
    self.db.execute("UPDATE links SET connector='0',updated='2020-01-01'");self.db.commit()
    result=self.observe(provider,fix(24,10.2))
    self.assertEqual(result.status,'unusableOrOldRoad')

  def test_no_curve_after_passage_and_no_geometry_cache_of_authority(self):
    road=curved_link();provider=self.provider(road)
    self.assertTrue(self.curves(self.warm(provider)))
    # New session downstream of the bend, with matching tangent bearing.
    provider.reset('newSession')
    p=road.points[-8]
    sample=replace(fix(0),lon=p[0],lat=p[1],bearing_deg=20.)
    self.observe(provider,sample)
    result=self.observe(provider,replace(sample,observed_at=10.1))
    self.assertEqual(result.status,'derived')
    self.assertFalse(self.curves(result))

  def test_bad_curve_does_not_drop_independently_reviewed_camera(self):
    road=replace(curved_link(),points=bend_points(radius=150.,step=35.))
    self.event(at=70.)
    result=self.warm(self.provider(road))
    self.assertFalse(self.curves(result))
    self.assertIn('sparseGeometry',result.curve_rejections)
    self.assertTrue(any(e.kind==RoadKind.CAMERA for e in result.road_input.snapshot.constraints))
