import copy
import json
import os
import unittest
from unittest.mock import patch
from dataclasses import replace

from ..sdk_events import parse,merge
from ..contract import RoadKind,RoadInputValidator
from ..offline import insert_link
from .. import ipc
from ..roadinputd import RoadInputService
from ..live import LiveSample
from . import test_offline as maps
from .test_b1_integration import Mailbox
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests import test_phone_kakao as phone_tests


def payload(now=10.,at=160.):
  return dict(version=1,session='paired-phone',sequence=1,source_at=now,expires=now+1.5,
    events=[dict(id='speed-1',code='KNSafetyCode_SpeedViolationCamera',limit_kph=36,
      geometry=[list(maps.point(x)) for x in (at-15,at,at+15)])])


class SdkEventTests(unittest.TestCase):
  def setUp(self):
    self.fixture=maps.OfflineTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
    self.provider=self.fixture.provider(maps.link())
    self.provider.observe(maps.fix(30.,now=10.),now=10.,today=maps.TODAY)
    self.road=self.provider.observe(maps.fix(32.,now=10.1),now=10.1,today=maps.TODAY).road_input
    self.assertIsNotNone(self.road)

  def test_real_projection_uses_directed_path_distance(self):
    result,deadline,count=merge(self.road,payload(),self.provider.store,10.1)
    camera=next(e for e in result.snapshot.constraints if e.kind==RoadKind.CAMERA)
    self.assertEqual(count,1);self.assertAlmostEqual(camera.start_m,128.,places=3)
    self.assertEqual(camera.target_speed,10.);self.assertAlmostEqual(deadline,11.5)
    self.assertEqual(result.context,self.road.context)
    self.assertEqual(RoadInputValidator().validate(result,10.1),'')

  def test_stale_future_or_malformed_geometry_never_adds_camera(self):
    variants=[]
    for key,value in [('source_at',11.),('expires',20.),('sequence',True)]:
      p=payload();p[key]=value;variants.append(p)
    for field,value in [('geometry',[[127.,37.]]*3),('limit_kph',float('nan')),('code','KNSafetyCode_SpeedViolationBackwardCamera')]:
      p=payload();p['events'][0][field]=value;variants.append(p)
    for p in variants:self.assertIsNone(parse(json.dumps(p),10.1))
    self.assertEqual(merge(self.road,payload(),self.provider.store,11.6)[2],0)
    self.assertIsNone(parse('x'*8193,10.1))

  def test_opposite_or_parallel_camera_is_withheld(self):
    p=payload();p['events'][0]['geometry'].reverse()
    self.assertEqual(merge(self.road,p,self.provider.store,10.1)[2],0)
    p=payload();p['events'][0]['geometry']=[list(maps.point(x,30.)) for x in (145,160,175)]
    self.assertEqual(merge(self.road,p,self.provider.store,10.1)[2],0)
    insert_link(self.fixture.db,maps.link('parallel',y=5.,start_node='p0',end_node='p1'));self.fixture.db.commit()
    self.assertEqual(merge(self.road,payload(),self.provider.store,10.1)[2],0)

  def test_outside_corridor_and_boundary_are_withheld(self):
    self.assertEqual(merge(self.road,payload(at=400.),self.provider.store,10.1)[2],0)
    self.assertEqual(merge(self.road,payload(at=10.),self.provider.store,10.1)[2],0)
    self.assertEqual(merge(None,payload(),self.provider.store,10.1)[2],0)

  def test_stronger_reviewed_camera_is_not_weakened(self):
    result,_,_=merge(self.road,payload(),self.provider.store,10.1)
    p=payload();p['events'][0]['limit_kph']=50
    again,_,_=merge(result,p,self.provider.store,10.1)
    self.assertEqual([e.target_speed for e in again.snapshot.constraints if e.kind==RoadKind.CAMERA],[10.])

  def test_capnp_hops_and_removal_between_raw_fixes(self):
    now=[100.];loc,roads=Mailbox(),Mailbox();clock=lambda:now[0]
    pub=ipc.LocationPublisher(clock=clock,socket=loc)
    reader=ipc.RoadReader(clock=clock,socket=roads)
    service=RoadInputService(str(self.fixture.path),clock=clock,today=lambda:maps.TODAY,
      reader=ipc.LocationReader(clock=clock,socket=loc),publisher=ipc.RoadPublisher(clock=clock,socket=roads))
    self.addCleanup(service.close)
    for i in range(1,5):
      now[0]=100.+i*.05
      sample=LiveSample(i,1,'accepted',maps.fix(30+i,now=now[0]),int((now[0]+.19)*1e9),1_000_000)
      pub.publish(sample,sdk_events=json.dumps(payload(now=now[0])))
      service.tick();road=reader(now[0])
    self.assertIsNotNone(road, (service.status,service.dataset_info,reader.__dict__))
    self.assertTrue(any(e.kind==RoadKind.CAMERA for e in road.snapshot.constraints))
    before=road.snapshot.sequence
    now[0]+=.02;pub.publish(sample,sdk_events='');service.tick();road=reader(now[0])
    self.assertIsNotNone(road);self.assertGreater(road.snapshot.sequence,before)
    self.assertFalse(any(e.kind==RoadKind.CAMERA for e in road.snapshot.constraints))
    now[0]+=.2;service.tick();self.assertIsNone(reader(now[0]))

  def test_pending_keeps_current_camera_only_until_its_original_sdk_expiry(self):
    from ..route_hint import RouteHint
    now=[100.];loc,roads=Mailbox(),Mailbox();clock=lambda:now[0]
    pub=ipc.LocationPublisher(clock=clock,socket=loc)
    reader=ipc.RoadReader(clock=clock,socket=roads)
    service=RoadInputService(str(self.fixture.path),clock=clock,today=lambda:maps.TODAY,
      reader=ipc.LocationReader(clock=clock,socket=loc),publisher=ipc.RoadPublisher(clock=clock,socket=roads))
    self.addCleanup(service.close)
    event=payload(now=100.05);raw=json.dumps(event)
    pending=RouteHint('pending','new',reason='rerouting')
    for i in range(1,37):
      now[0]=100.+i*.05
      sample=LiveSample(i,1,'accepted',maps.fix(30+i,now=now[0]),int((now[0]+.19)*1e9),1_000_000)
      pub.publish(sample,pending,sdk_events=raw);service.tick();road=reader(now[0])
      if i<3:continue
      self.assertTrue(service.adapter.observation.route_independent)
      self.assertEqual([r.road_id for r in road.context.path],['a'])
      cameras=[e for e in road.snapshot.constraints if e.kind==RoadKind.CAMERA]
      self.assertEqual(bool(cameras),now[0]<event['expires'])
      if cameras:self.assertLessEqual(reader.valid_until,event['expires'])
    now[0]+=.2;service.tick();self.assertIsNone(reader(now[0]))

  def test_pending_cannot_qualify_sdk_camera_on_next_link(self):
    from ..route_hint import RouteHint
    from .test_route_hint import RouteHintTests
    a,b,c=RouteHintTests().fork()
    # Reuse the current fixture store and add only the two future branches.
    insert_link(self.fixture.db,b);insert_link(self.fixture.db,c);self.fixture.db.commit()
    result=self.provider.revalidate_route(now=10.2,today=maps.TODAY,route=RouteHint('pending','new'))
    self.assertEqual([r.road_id for r in result.road_input.context.path],['a'])
    self.assertEqual(merge(result.road_input,payload(at=450),self.provider.store,10.2)[2],0)


class PairedSdkTests(unittest.TestCase):
  def setUp(self):
    self.enterContext(patch.dict(os.environ,KOREAN_ROAD_INPUT='1'))
    self.base=phone_tests.PhoneKakaoTest();self.base.setUp();self.addCleanup(self.base.doCleanups)
    self.kakao=self.base.kakao;self.owner=self.base.service.session(self.base.token)['id']
    self.data=copy.deepcopy(self.base.payload)
    raw=payload(now=100.)['events'][0]
    self.data.update(event_geometry_version=1,sdk_simulation=False,gps_valid=False)
    self.data['events']=[dict(raw,kind='camera',distance_m=None,distance_basis='unknown',passed=False,variable=False)]

  def test_paired_source_time_and_owner_are_preserved(self):
    self.base.accept(self.data)
    raw=self.kakao.road_events(self.owner);self.assertTrue(raw)
    data=parse(raw,100.);self.assertAlmostEqual(data['source_at'],99.98)
    self.assertEqual(self.kakao.road_events('another-owner'),'')
    self.base.now+=1.5;self.assertEqual(self.kakao.road_events(self.owner),'')
    self.assertEqual(self.base.store.writes,[])

  def test_home_revocation_and_simulation_cannot_feed_control(self):
    self.data['sdk_simulation']=True;self.base.accept(self.data)
    self.assertEqual(self.kakao.road_events(self.owner),'')
    self.base.service.device_revoke(self.owner);self.assertEqual(self.kakao.road_events(self.owner),'')

  def test_home_mode_blocks_geometry_and_gps_capability(self):
    self.base.accept(self.data)
    self.base.service.mode='home_receive'
    self.assertFalse(self.kakao.driving_input_allowed())
    self.assertEqual(self.kakao.road_events(self.owner),'')

  def test_passed_variable_and_unsupported_codes_not_qualified(self):
    for field,value in [('passed',True),('variable',True),('code','KNSafetyCode_SignalViolationCamera')]:
      self.data['challenge']=self.kakao.challenge(self.base.token)['challenge'];self.data['seq']+=1
      d=copy.deepcopy(self.data);d['events'][0][field]=value;self.base.accept(d)
      self.assertEqual(parse(self.kakao.road_events(self.owner),100.)['events'],[])
