"""Typed two-hop IPC with 1Hz GPS / synthetic vehicle motion. No hardware writes."""
import json
import unittest
from dataclasses import replace
from types import SimpleNamespace

from cereal import messaging,log
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints import ipc
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.live import LiveReceiver, NS
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.motion import MotionSample
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.motion_runtime import VehicleMotionReader
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.roadinputd import RoadInputService
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.tests import test_offline as maps
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.route_hint import RouteHint


class Mailbox:
  def __init__(self):self.packet=None
  def send(self,p):self.packet=p
  def receive(self,**kw):p,self.packet=self.packet,None;return p


class Motion:
  def __init__(self):self.valid=True;self.status='syntheticMotion'
  def sample(self,now):return MotionSample(now,10.,0.) if self.valid else None
  def close(self):pass


class RuntimeMotionTests(unittest.TestCase):
  def setUp(self):
    self.maps=maps.OfflineTests();self.maps.setUp();self.maps.provider()
    self.now=100.;self.motion=Motion();self.rx=LiveReceiver()
    self.stream='11111111-1111-4111-8111-111111111111'
    self.seq=0;self.sync_seq=0
    self.loc,self.roadbox=Mailbox(),Mailbox()
    clock=lambda:self.now
    self.pub=ipc.LocationPublisher(clock=clock,socket=self.loc)
    self.service=RoadInputService(self.maps.path,clock=clock,today=lambda:maps.TODAY,
      reader=ipc.LocationReader(clock=clock,socket=self.loc),publisher=ipc.RoadPublisher(clock=clock,socket=self.roadbox),motion_reader=self.motion)
    self.reader=ipc.RoadReader(clock=clock,socket=self.roadbox)
    self.route=RouteHint()
    self.sync()

  def tearDown(self):self.service.close();self.reader.close();self.pub.close();self.maps.tearDown()

  def sync(self):
    self.sync_seq+=1
    sent=round((self.now-90)*NS)
    reply=self.rx.begin('synthetic',dict(stream=self.stream,sync_sequence=self.sync_seq,phone_send_ns=sent),round(self.now*NS))
    self.sync_id=reply['sync_id']
    self.now+=.025
    self.rx.commit(dict(sync_id=self.sync_id,phone_receive_ns=sent+40_000_000),round(self.now*NS))

  def gps(self):
    self.seq+=1
    fix_time=self.now-.06
    phone_at=round((fix_time-89.98)*NS)
    self.rx.accept(dict(stream=self.stream,sync_id=self.sync_id,sequence=self.seq,fix_elapsed_ns=phone_at,
      received_elapsed_ns=phone_at+10_000_000,sent_elapsed_ns=phone_at+20_000_000,
      longitude=maps.point(20+10*(fix_time-100))[0],latitude=maps.point(0)[1],bearing_deg=90.,speed_mps=10.,
      accuracy_m=2.,bearing_accuracy_deg=2.,provider='gps',mock=False),round(self.now*NS))

  def tick(self,t,gps=False,publish=True):
    self.now=round(t,8)
    if gps:self.gps()
    if publish:self.pub.publish(self.rx.sample(round(self.now*NS)),self.route)
    self.service.tick()
    return self.reader(self.now)

  def warm(self):
    road=None
    for i in range(1,51):road=self.tick(100.05+i*.05,gps=i in (10,30,50))
    self.assertIsNotNone(road)
    return road

  def test_one_hz_survives_original_fix_expiry_with_provenance(self):
    available=[]
    for i in range(1,71):
      road=self.tick(100.05+i*.05,gps=i in (10,30,50,70))
      if i>=30:available.append(road is not None)
      if road is not None:
        self.assertTrue(road.context.motion_estimated)
        self.assertLess(road.context.gps_observed_at,road.context.observed_at)
        self.assertGreater(road.context.position_error_m,2.)
        self.assertLessEqual(self.reader.valid_until,self.now+.15+1e-8)
    self.assertTrue(all(available))
    self.assertIsNone(self.rx.sample(round((self.now+.2)*NS)).fix)

  def test_gps_silence_expires_anchor_even_while_motion_and_publishers_continue(self):
    self.warm()
    for i in range(1,28):road=self.tick(102.55+i*.05)
    self.assertIsNone(road)
    self.assertIsNone(self.service.reader.latest.anchor)

  def test_publisher_loss_clears_anchor_before_one_hz_limit(self):
    self.warm()
    road=self.tick(102.76,publish=False)
    self.assertIsNone(road)
    self.assertIsNone(self.service.reader.latest.anchor)

  def test_missing_motion_or_authorization_revokes_immediately(self):
    self.warm();self.motion.valid=False
    self.assertIsNone(self.tick(102.6))
    self.motion.valid=True;self.rx.clear('authorizationEnded',unsync=True)
    self.assertIsNone(self.tick(102.65))
    self.assertIsNone(self.service.reader.latest.anchor)

  def test_compatible_clock_renewal_preserves_anchor_deadline(self):
    self.warm();before=self.rx.sample(round(self.now*NS));self.sync()
    after=self.rx.sample(round(self.now*NS))
    self.assertEqual(after.anchor_until_ns,before.anchor_until_ns)
    self.assertEqual(after.generation,before.generation)
    self.assertIsNotNone(self.tick(self.now+.025))

  def assert_current_only(self, road):
    self.assertIsNotNone(road)
    self.assertTrue(self.service.adapter.observation.route_independent)
    self.assertEqual([r.road_id for r in road.context.path],['a'])
    self.assertTrue(all(c.link.road_id=='a' for c in road.snapshot.constraints))

  def test_route_pending_rebuilds_current_road_and_labels_limited_scope(self):
    self.warm();self.route=RouteHint('pending','new',reason='rerouting')
    self.assert_current_only(self.tick(102.6))
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.road_status import RoadStatusMonitor,describe
    monitor=RoadStatusMonitor(clock=lambda:self.now);monitor.attach(self.reader);monitor.update()
    self.assertIn('도로 정보: 현재 도로만 확인',describe(monitor.view(),False))

  def active_route(self, identity='restored'):
    return RouteHint('active',identity,tuple(maps.point(x) for x in range(0,351,50)),self.now+.15)

  def test_route_recovers_between_fixes_without_renewing_original_anchor(self):
    old=self.warm();anchor=self.rx.sample(round(self.now*NS))
    self.route=RouteHint('pending','new',reason='rerouting')
    for i in range(1,11):self.assert_current_only(self.tick(102.55+i*.05))
    self.route=self.active_route()
    new=self.tick(103.1)
    self.assertIsNotNone(new)
    self.assertEqual(new.context.gps_observed_at,old.context.gps_observed_at)
    self.assertEqual(new.context.gps_uncertainty_s,old.context.gps_uncertainty_s)
    self.assertEqual(new.snapshot.source_at,old.snapshot.source_at)
    self.assertEqual(new.snapshot.received_at,old.snapshot.received_at)
    self.assertEqual(self.service.reader.latest.anchor_until_ns,anchor.anchor_until_ns)
    self.assertLessEqual(self.reader.valid_until,anchor.anchor_until_ns/NS)

  def test_long_pending_uses_fresh_current_road_without_restoring_future_path(self):
    self.warm();self.route=RouteHint('pending','new',reason='rerouting')
    for i in range(1,66):
      if i%30==5:self.sync()
      self.assert_current_only(self.tick(102.55+i*.05,gps=i%20==0))
    self.assertTrue(self.service.adapter.observer.tracker.confirmed)
    self.route=self.active_route()
    self.assertIsNotNone(self.tick(self.now+.05))

  def test_repeated_invalid_expired_route_packets_do_not_preserve_anchor(self):
    self.warm();self.route=self.active_route('same')
    self.assertIsNotNone(self.tick(102.6))
    for i in range(2,12):
      road=self.tick(102.55+i*.05)
      if self.now>=self.route.valid_until:self.assertIsNone(road)
    self.route=self.active_route('same')
    self.assertIsNone(self.tick(self.now+.05))

  def test_pending_gps_expiry_cannot_be_repaired_by_a_route_heartbeat(self):
    self.warm();self.route=RouteHint('pending','new',reason='rerouting')
    deadline=self.rx.sample(round(self.now*NS)).anchor_until_ns/NS
    for i in range(1,28):
      road=self.tick(102.55+i*.05)
      if self.now>=deadline:self.assertIsNone(road)
      else:self.assert_current_only(road)
    self.route=self.active_route()
    self.assertIsNone(self.tick(self.now+.05))
    self.assertIsNone(self.tick(self.now+.05,gps=True))

  def test_motion_loss_during_pending_requires_new_gps_confirmation(self):
    self.warm();self.route=RouteHint('pending','new',reason='rerouting')
    self.motion.valid=False;self.assertIsNone(self.tick(102.6))
    self.motion.valid=True
    for i in range(2,6):self.assertIsNone(self.tick(102.55+i*.05))
    self.route=self.active_route()
    self.assertIsNone(self.tick(self.now+.05))
    self.assertIsNone(self.tick(self.now+.05,gps=True))

  def test_route_recovery_cannot_restore_a_revoked_authorization(self):
    self.warm();self.route=RouteHint('pending','new',reason='rerouting')
    self.assert_current_only(self.tick(102.6));self.rx.clear('authorizationEnded',unsync=True)
    self.route=self.active_route()
    self.assertIsNone(self.tick(102.65))

  def test_recovery_rechecks_route_geometry_before_publishing(self):
    self.warm();self.route=RouteHint('pending','new',reason='rerouting')
    self.assert_current_only(self.tick(102.6))
    self.route=replace(self.active_route(),points=tuple(maps.point(x,30) for x in range(0,351,50)))
    self.assertIsNone(self.tick(102.65))
    self.route=self.active_route('valid-again')
    self.assertIsNone(self.tick(102.7))

  def test_ipc_cannot_extend_anchor_or_omit_new_schema(self):
    self.warm();sample=self.rx.sample(round(self.now*NS))
    self.pub.publish(replace(sample,anchor_until_ns=sample.anchor_until_ns+NS))
    self.service.tick();self.assertIsNone(self.reader(self.now))
    self.pub.publish(sample)
    with messaging.log.Event.from_bytes(self.loc.packet) as msg:
      bad=msg.as_builder();bad.phoneRoadLocationSP.schemaVersion=1;self.loc.packet=bad.to_bytes()
    self.service.tick();self.assertIsNone(self.reader(self.now))

  def test_status_labels_estimation_without_claiming_new_gps_and_expires(self):
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.road_status import RoadStatusMonitor,describe
    self.warm()
    for _ in range(5):self.tick(self.now+.05)
    self.assertIsNone(self.service.reader.latest.fix)
    monitor=RoadStatusMonitor(clock=lambda:self.now);monitor.attach(self.reader);monitor.update()
    text=describe(monitor.view(),False)
    self.assertIn('위치: 차량 이동으로 추정 중',text)
    self.assertIn('도로 정보: 확인됨',text)
    self.assertNotIn('GPS: 위치 수신 중',text)
    self.now+=.2
    state=monitor.view();self.assertFalse(state['input_available']);self.assertFalse(state['motion_estimated'])
    self.assertNotIn('위치: 차량 이동으로 추정 중',describe(state,False))

  def test_old_road_schema_cannot_hide_estimation(self):
    self.warm();self.now+=.05;self.pub.publish(self.rx.sample(round(self.now*NS)))
    self.service.tick()
    with messaging.log.Event.from_bytes(self.roadbox.packet) as msg:
      bad=msg.as_builder();self.assertEqual(bad.roadConstraintsSP.schemaVersion,2)
      bad.roadConstraintsSP.schemaVersion=1;self.roadbox.packet=bad.to_bytes()
    self.assertIsNone(self.reader(self.now))


class VehicleMotionTests(unittest.TestCase):
  def fixture(self):
    class SM(dict):
      def update(self,*args):pass
      def all_checks(self,*args):return True
    sm=SM()
    for name in VehicleMotionReader.SERVICES:sm[name]=getattr(messaging.new_message(name),name)
    sm.logMonoTime={name:100*NS for name in sm}
    cs=sm['carState'];cs.canValid=True;cs.gearShifter='drive';cs.vEgo=10.
    p=sm['livePose'];p.timestamp=100*NS;p.inputsOK=p.sensorsOK=p.posenetOK=True
    p.angularVelocityDevice.valid=True;p.angularVelocityDevice.z=.1
    p.angularVelocityDevice.xStd=p.angularVelocityDevice.yStd=p.angularVelocityDevice.zStd=.001
    c=sm['liveCalibration'];c.calStatus='calibrated';c.rpyCalib=[0.,0.,0.];c.rpyCalibSpread=[.001]*3
    return sm,VehicleMotionReader(sm)

  def test_actual_pose_timestamp_and_calibrated_yaw_are_preserved(self):
    sm,r=self.fixture();v=r.sample(100.01)
    self.assertAlmostEqual(v.yaw_clockwise_rad_s,.1,places=6);self.assertEqual(v.observed_at,100.)
    self.assertIsNone(r.sample(100.02));self.assertTrue(r.valid)

  def test_missing_yaw_is_not_straight_motion(self):
    sm,r=self.fixture();sm['livePose'].angularVelocityDevice.valid=False
    self.assertIsNone(r.sample(100.01));self.assertFalse(r.valid)

  def test_republished_old_pose_invalid_even_if_envelopes_are_fresh(self):
    sm,r=self.fixture();sm.logMonoTime={name:101*NS for name in sm}
    self.assertIsNone(r.sample(101));self.assertFalse(r.valid)

  def test_reverse_invalid_can_calibration_and_uncertainty_block(self):
    for case in ('reverse','can','calibration','uncertainty'):
      sm,r=self.fixture()
      if case=='reverse':sm['carState'].gearShifter='reverse'
      elif case=='can':sm['carState'].canValid=False
      elif case=='calibration':sm['liveCalibration'].calStatus='uncalibrated'
      else:sm['livePose'].angularVelocityDevice.zStd=.1
      self.assertIsNone(r.sample(100.01),case);self.assertFalse(r.valid)
