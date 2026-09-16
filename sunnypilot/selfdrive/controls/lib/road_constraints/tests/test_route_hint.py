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
  def test_expired_pending_and_reversed_routes_produce_no_input(self):
    a=replace(link(),points=tuple(point(x) for x in range(0,301,5)));p=self.provider(a)
    for h in (replace(self.hint(a.points),valid_until=9.),RouteHint('pending','phone:2',reason='rerouting'),self.hint(tuple(reversed(a.points)))):
      self.assertIsNone(self.warm(p,h).road_input)
  def test_mismatched_route_and_sparse_geometry_withheld(self):
    a=replace(link(),points=tuple(point(x) for x in range(0,301,5)));p=self.provider(a)
    for h in (self.hint(tuple(point(x,30.) for x in range(0,301,5))),self.hint((point(0),point(300)))):
      self.assertIsNone(self.warm(p,h).road_input)
  def test_route_change_requires_new_warmup(self):
    a,b,straight=self.fork();p=self.provider(a,b,straight);h=self.hint(a.points+b.points[1:]);self.warm(p,h,x=100)
    new=replace(self.hint(a.points+straight.points[1:]),identity='phone:2')
    self.assertEqual(self.observe(p,fix(104,10.2),new).status,'warmingUp')
    result=self.observe(p,fix(106,10.3),new)
    self.assertEqual([r.road_id for r in result.road_input.context.path],['a','straight'])
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
