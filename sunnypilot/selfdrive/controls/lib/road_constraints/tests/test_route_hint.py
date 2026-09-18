import math
import unittest
from dataclasses import replace
from . import test_offline as fixtures
from .test_offline import link,point,fix
from .test_curves import curved_link
from ..route_hint import RouteHint,RouteShape,RouteCorridor
from ..contract import RoadKind

class RouteHintTests(unittest.TestCase):
  setUp=fixtures.OfflineTests.setUp
  tearDown=fixtures.OfflineTests.tearDown
  provider=fixtures.OfflineTests.provider
  def shape(self,road):return RouteShape(road.points)
  def hint(self,points,at=10.):return RouteHint('active','phone:1',tuple(points),at+3.)
  def observe(self,p,f,h):return p.observe(f,now=f.observed_at,today=fixtures.TODAY,route=h)
  def warm(self,p,h,x=20):
    self.observe(p,fix(x,10.),h)
    return self.observe(p,fix(x+2,10.1),h)
  def fork(self):
    a=replace(link('a'),points=tuple(point(x) for x in range(0,301,5)))
    b=replace(curved_link('bend',lead=60,tail=180),start='n1',end='nb')
    b=replace(b,points=tuple((p[0]+point(300)[0]-point(0)[0],p[1]) for p in b.points))
    straight=replace(link('straight',300,800,start_node='n1',end_node='ns'),points=tuple(point(x) for x in range(300,801,5)))
    return a,b,straight
  def test_unique_route_selects_curved_fork_and_candidate(self):
    a,b,straight=self.fork();p=self.provider(a,b,straight)
    h=self.hint(a.points+b.points[1:]);result=self.warm(p,h,x=100)
    self.assertEqual(result.status,'derived')
    self.assertEqual([r.road_id for r in result.road_input.context.path],['a','bend'])
    self.assertTrue(any(c.kind==RoadKind.CURVE and c.link.road_id=='bend' for c in result.road_input.snapshot.constraints))
  def test_other_branch_route_withholds_wrong_curve(self):
    a,b,straight=self.fork();p=self.provider(a,b,straight)
    result=self.warm(p,self.hint(a.points+straight.points[1:]),x=100)
    self.assertEqual([r.road_id for r in result.road_input.context.path],['a','straight'])
    self.assertFalse(any(c.link.road_id=='bend' for c in result.road_input.snapshot.constraints))
  def test_no_route_keeps_original_fork_hold(self):
    a,b,straight=self.fork();p=self.provider(a,b,straight)
    result=self.warm(p,None,x=100)
    self.assertEqual(result.horizon_end,'fork');self.assertEqual(len(result.road_input.context.path),1)
  def test_route_does_not_override_parallel_current_road_ambiguity(self):
    a=replace(link(),points=tuple(point(x) for x in range(0,301,5)))
    p=self.provider(a,link('parallel',y=4.))
    self.assertEqual(self.warm(p,self.hint(a.points)).status,'ambiguousRoad')
  def test_expired_pending_routes_use_current_road_only_and_reversed_route_is_blocked(self):
    a=replace(link(),points=tuple(point(x) for x in range(0,301,5)));p=self.provider(a)
    for h in (replace(self.hint(a.points),valid_until=9.),RouteHint('pending','phone:2',reason='rerouting')):
      p.reset('new-case');result=self.warm(p,h)
      self.assertTrue(result.route_independent)
      self.assertEqual([r.road_id for r in result.road_input.context.path],['a'])
    p.reset('new-case')
    self.assertIsNone(self.warm(p,self.hint(tuple(reversed(a.points)))).road_input)
  def test_mismatched_route_and_sparse_geometry_withheld(self):
    a=replace(link(),points=tuple(point(x) for x in range(0,301,5)));p=self.provider(a)
    for h in (self.hint(tuple(point(x,30.) for x in range(0,301,5))),self.hint((point(0),point(300)))):
      self.assertIsNone(self.warm(p,h).road_input)
  def test_route_change_rebuilds_branch_from_independent_current_road(self):
    a,b,straight=self.fork();p=self.provider(a,b,straight);h=self.hint(a.points+b.points[1:]);self.warm(p,h,x=100)
    new=replace(self.hint(a.points+straight.points[1:]),identity='phone:2')
    result=self.observe(p,fix(104,10.2),new)
    self.assertEqual([r.road_id for r in result.road_input.context.path],['a','straight'])
    self.assertFalse(any(c.link.road_id=='bend' for c in result.road_input.snapshot.constraints))

  def test_revalidation_rebuilds_branch_without_manufacturing_a_fix(self):
    a,b,straight=self.fork();p=self.provider(a,b,straight)
    old=self.warm(p,self.hint(a.points+b.points[1:]),x=100).road_input
    original=p.previous_fix
    new=replace(self.hint(a.points+straight.points[1:]),identity='phone:2')
    result=p.revalidate_route(now=10.6,today=fixtures.TODAY,route=new).road_input
    self.assertIs(p.previous_fix,original)
    self.assertEqual(result.context.observed_at,old.context.observed_at)
    self.assertEqual(result.snapshot.source_at,old.snapshot.source_at)
    self.assertEqual(result.snapshot.received_at,old.snapshot.received_at)
    self.assertEqual([r.road_id for r in result.context.path],['a','straight'])
    self.assertFalse(any(c.link.road_id=='bend' for c in result.snapshot.constraints))

  def test_pending_tracks_current_road_but_never_supplies_future_branch(self):
    a,b,straight=self.fork();p=self.provider(a,b,straight)
    pending=RouteHint('pending','phone:2',reason='rerouting')
    current=self.warm(p,pending,x=100)
    self.assertTrue(current.route_independent)
    self.assertEqual([r.road_id for r in current.road_input.context.path],['a'])
    self.assertFalse(any(c.kind==RoadKind.CURVE for c in current.road_input.snapshot.constraints))
    new=self.hint(a.points+straight.points[1:])
    result=p.revalidate_route(now=10.2,today=fixtures.TODAY,route=new)
    self.assertEqual([r.road_id for r in result.road_input.context.path],['a','straight'])

  def test_revalidation_requires_two_measured_matches_and_original_deadline(self):
    a,b,c=self.fork();p=self.provider(a,b,c);h=self.hint(a.points+b.points[1:])
    self.observe(p,fix(100,10.),h)
    self.assertIsNone(p.revalidate_route(now=10.1,today=fixtures.TODAY,route=h).road_input)
    self.observe(p,fix(102,10.1),h)
    self.assertIsNone(p.revalidate_route(now=11.11,today=fixtures.TODAY,route=h).road_input)

  def test_revalidation_drops_expired_branch_and_rejects_mismatched_route(self):
    a,b,c=self.fork();p=self.provider(a,b,c);h=self.hint(a.points+b.points[1:])
    self.warm(p,h,x=100)
    expired=p.revalidate_route(now=10.2,today=fixtures.TODAY,route=replace(h,valid_until=10.15))
    self.assertTrue(expired.route_independent)
    self.assertEqual([r.road_id for r in expired.road_input.context.path],['a'])
    wrong=replace(h,identity='wrong',points=tuple(point(x,30) for x in range(0,701,5)))
    self.assertIsNone(p.revalidate_route(now=10.3,today=fixtures.TODAY,route=wrong).road_input)
    self.assertIsNone(p.revalidate_route(now=10.4,today=fixtures.TODAY,route=h).road_input)

  def test_pending_does_not_follow_even_a_unique_successor(self):
    a,b,_=self.fork();p=self.provider(a,b)
    h=self.hint(a.points+b.points[1:]);self.warm(p,h,x=100)
    result=p.revalidate_route(now=10.2,today=fixtures.TODAY,route=RouteHint('pending','new'))
    self.assertEqual([r.road_id for r in result.road_input.context.path],['a'])
    self.assertTrue(all(c.link.road_id=='a' for c in result.road_input.snapshot.constraints))

  def test_pending_does_not_bypass_current_road_ambiguity(self):
    a,b,c=self.fork();p=self.provider(a,b,c,replace(a,id='parallel',points=tuple(point(x,4) for x in range(0,301,5))))
    self.assertIsNone(self.warm(p,RouteHint('pending','new'),x=100).road_input)
  def test_both_branch_geometries_matching_route_are_held(self):
    a,b,straight=self.fork();p=self.provider(a,b,replace(b,id='duplicate',end='other'))
    result=self.warm(p,self.hint(a.points+b.points[1:]),x=100)
    self.assertEqual(result.horizon_end,'routeBranchAmbiguous');self.assertEqual(len(result.road_input.context.path),1)
  def test_window_keeps_original_coordinates_with_bounded_work(self):
    points=tuple(point(x) for x in range(65536));shape=RouteShape(points)
    result,reason=shape.window(fix(30000))
    self.assertEqual(reason,'');self.assertLessEqual(len(result),1024);self.assertIn(result[0],points)
    self.assertLess(distance_between(result[0],point(30000)),5.)
  def test_loop_and_overlapping_route_window_rejected(self):
    points=tuple(point(x) for x in range(0,101,5))*2
    self.assertEqual(RouteShape(points).window(fix(20))[1],'routeGeometryAmbiguous')
  def test_wire_rejects_expired_large_and_nonfinite(self):
    h=self.hint((point(0),point(20)))
    self.assertEqual(RouteHint.parse(h.wire(),10.),h)
    for raw in (replace(h,valid_until=9.).wire(),replace(h,points=(point(0),)*1025).wire(),replace(h,valid_until=math.inf).wire(),replace(h,state='pending').wire()):
      with self.assertRaises(ValueError):RouteHint.parse(raw,10.)

def distance_between(a,b):
  from ..offline import distance
  return distance(a,b)
