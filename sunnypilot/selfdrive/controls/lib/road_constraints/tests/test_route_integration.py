import hashlib
import sqlite3
import struct
import unittest
from dataclasses import replace
from . import test_b1_integration as base
from . import test_route_hint as hints
from ..offline import create_schema,insert_link
from ..route_hint import RouteHint

class RouteIntegrationTests(base.Fixture,unittest.TestCase):
  setUp=base.B1IntegrationTests.setUp
  pair=base.B1IntegrationTests.pair
  synchronize=base.B1IntegrationTests.synchronize
  receive=base.B1IntegrationTests.receive
  report=base.B1IntegrationTests.report

  def setup_route(self):
    import os
    a,b,c=hints.RouteHintTests().fork()
    temp=self.fixture.path.with_name('fork.sqlite')
    with sqlite3.connect(temp) as db:
      create_schema(db);db.execute("INSERT INTO metadata VALUES('dataset_id','synthetic-route-fork')")
      for road in (a,b,c):insert_link(db,road)
    os.replace(temp,self.fixture.path)
    self.route_points=list(a.points+b.points[1:])
    digest=hashlib.sha256(b''.join(struct.pack('>dd',*p) for p in self.route_points)).hexdigest()
    self.route_frame={'protocol':2,'challenge':'','seq':1,'revision':1,'state':'active','destination':'합성 곡선 분기',
      'shape_id':digest,'point_count':len(self.route_points),'geometry_status':'full','total_m':1000,'total_s':100,
      'remaining_m':900,'remaining_s':90,'location_age_ms':0,'matched':True}
    self.send_route()
    api=self.service.route
    api.chunk(self.token,self.csrf,{'challenge':api.challenge(self.token)['challenge'],'seq':2,'revision':1,
      'shape_id':digest,'offset':0,'points':[list(p) for p in self.route_points]})

  def send_route(self,**changes):
    self.route_frame.update(changes)
    self.route_frame['challenge']=self.service.route.challenge(self.token)['challenge']
    self.route_frame['seq']=self.service.session(self.token).get('route_seq',0)+1
    return self.service.route.accept(self.token,self.csrf,self.route_frame)

  def tick(self,x):
    self.receive(x);self.runtime.update(base.SM(self.now),10,True)
    sample=self.api.sample();hint=self.service.route.hint(self.api.receiver.owner,sample.fix)
    self.publisher.publish(sample,hint);self.deriver.tick()
    self.observer.update(self.sm,self.cp,.05,0.,'e2e',True)

  def warm(self):
    for x in (100,102,104,106,108,110):self.tick(x)

  def test_complete_phone_route_crosses_capnp_to_fork_curve_observer(self):
    self.setup_route();self.warm()
    road=self.reader.road
    self.assertIsNotNone(road)
    self.assertEqual([r.road_id for r in road.context.path],['a','bend'])
    self.assertEqual(self.observer.plan.kind,'curve')
    report=self.report();self.assertTrue(report.observationOnly);self.assertFalse(report.selected)
    self.assertEqual(report.selectedAcceleration,0.);self.assertEqual(self.store.writes,[])

  def test_rerouting_and_expiry_clear_old_candidate_without_new_gps(self):
    self.setup_route();self.warm();self.assertEqual(self.observer.plan.kind,'curve')
    self.send_route(location_age_ms=4000)
    sample=self.api.sample();self.publisher.publish(sample,self.service.route.hint(self.api.receiver.owner,sample.fix))
    self.deriver.tick();self.observer.update(self.sm,self.cp,.05,0.,'e2e',True)
    self.assertIsNone(self.reader.road);self.assertIsNone(self.observer.plan.acceleration)
    self.send_route(location_age_ms=0)
    self.tick(112);self.assertIsNone(self.reader.road)
    self.tick(114);self.tick(116);self.assertIsNotNone(self.reader.road)
    self.send_route(revision=2,state='rerouting',shape_id='',point_count=0,geometry_status='unavailable',matched=False,
      location_age_ms=None,total_m=None,total_s=None,remaining_m=None,remaining_s=None)
    self.tick(118);self.assertIsNone(self.reader.road)

  def test_hint_deadline_and_invalid_payload_cannot_refresh_old_branch(self):
    self.setup_route();self.warm()
    sample=self.api.sample();hint=self.service.route.hint(self.api.receiver.owner,sample.fix)
    self.publisher.publish(sample,replace(hint,valid_until=self.now-1))
    self.deriver.tick();self.observer.update(self.sm,self.cp,.05,0.,'e2e',True)
    self.assertIsNone(self.reader.road)

  def test_route_end_reconfirms_free_drive_without_old_fork(self):
    self.setup_route();self.warm()
    self.send_route(revision=2,state='ended',shape_id='',point_count=0,geometry_status='unavailable',matched=False,
      location_age_ms=None,total_m=None,total_s=None,remaining_m=None,remaining_s=None)
    self.tick(112);self.assertIsNone(self.reader.road)
    self.tick(114);self.tick(116)
    self.assertEqual([r.road_id for r in self.reader.road.context.path],['a'])
