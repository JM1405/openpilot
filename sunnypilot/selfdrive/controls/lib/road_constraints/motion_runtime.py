"""Read-only vehicle motion + authenticated GPS anchor -> typed road position.

No controller/Params/network writes. GPS age, motion age, authentication epoch,
route and dataset lifetimes remain independent. Missing yaw is never zero yaw.
"""
from dataclasses import replace
from datetime import date
import math

from cereal import log, messaging
from openpilot.selfdrive.locationd.helpers import Pose, PoseCalibrator
from .live import NS, FIX_AGE_NS
from .motion import MotionSample
from .motion_shadow import MotionRoadObserver
from .offline import Observation


class VehicleMotionReader:
  SERVICES=('carState','livePose','liveCalibration')

  def __init__(self, sm=None):
    self.sm=sm if sm is not None else messaging.SubMaster(list(self.SERVICES))
    self.calibrator=PoseCalibrator()
    self.last_at=-1.
    self.valid=False
    self.status='waitingForVehicleMotion'

  def sample(self, now):
    self.valid=False
    try:
      self.sm.update(0)
      if not self.sm.all_checks(list(self.SERVICES)):
        raise ValueError('vehicleMotionUnavailable')
      cs,pose,cal=(self.sm[n] for n in self.SERVICES)
      stamps=[self.sm.logMonoTime[n]/NS for n in self.SERVICES]
      pose_at=pose.timestamp/NS
      if (not all(math.isfinite(t) and t>0 for t in (*stamps,pose_at))
          or not 0<=now-stamps[0]<=.1 or not 0<=now-stamps[1]<=.1
          or not 0<=now-pose_at<=.1 or pose_at>stamps[1]+.01
          or not 0<=now-stamps[2]<=2. or not cs.canValid or str(cs.gearShifter)!='drive'
          or cs.vehicleSensorsInvalid or not math.isfinite(cs.vEgo) or not 0<=cs.vEgo<=70
          or not (pose.inputsOK and pose.sensorsOK and pose.posenetOK and pose.angularVelocityDevice.valid)
          or cal.calStatus!=log.LiveCalibrationData.Status.calibrated):
        raise ValueError('invalidVehicleMotion')
      rpy=list(cal.rpyCalib);spread=list(cal.rpyCalibSpread)
      omega=pose.angularVelocityDevice
      if (len(rpy)!=3 or len(spread)!=3 or not all(math.isfinite(v) for v in (*rpy,*spread))
          or any(abs(v)>.03 for v in spread)
          or not all(math.isfinite(v) for v in (omega.x,omega.y,omega.z,omega.xStd,omega.yStd,omega.zStd))
          or min(omega.xStd,omega.yStd,omega.zStd)<0
          or math.hypot(omega.xStd,omega.yStd,omega.zStd)>.03):
        raise ValueError('uncertainVehicleYaw')
      self.calibrator.feed_live_calib(cal)
      calibrated=self.calibrator.build_calibrated_pose(Pose.from_live_pose(pose))
      # Calibrated frame: forward/right/down, so +z is clockwise heading.
      yaw=float(calibrated.angular_velocity.z)
      if not math.isfinite(yaw) or abs(yaw)>1.2:
        raise ValueError('invalidVehicleYaw')
      at=min(stamps[0],pose_at)
      if at<self.last_at:
        raise ValueError('vehicleMotionReplay')
      self.valid=True;self.status='vehicleMotion'
      if at==self.last_at:
        return None  # Heartbeats never manufacture independent motion samples.
      self.last_at=at
      return MotionSample(at,float(cs.vEgo),yaw)
    except Exception as exc:
      self.status=str(exc) if isinstance(exc,ValueError) else 'vehicleMotionError'
      return None

  def close(self):
    self.sm=None


class RoadMotionAdapter:
  def __init__(self, sample, store, motion, *, route=None, today=date.today):
    self.sample=sample;self.motion=motion;self.route=route;self.today=today
    self.observer=MotionRoadObserver(store,today=today())
    self.generation=-1;self.last_fix=-1.;self.last_motion_valid=True
    self.observation=Observation('waitingForVehicleMotion')
    self.valid_until=0.

  def __call__(self, now):
    item=self.sample()
    if item.generation!=self.generation:
      self.observer.revoke(item.status)
      self.generation=item.generation
      self.last_fix=-1.
    self.observer.set_route(self.route() if self.route is not None else None)
    motion=self.motion.sample(now)
    if not self.motion.valid:
      if self.last_motion_valid:
        self.observer.revoke(self.motion.status)
      self.last_motion_valid=False
      self.observation=Observation(self.motion.status);self.valid_until=0.
      return None
    self.last_motion_valid=True
    if motion is not None:
      self.observer.push_motion(motion,now=now)
    anchor=item.anchor
    if anchor is None or now*NS>=item.anchor_until_ns:
      self.observation=Observation(item.status);self.valid_until=0.
      return None
    if anchor.observed_at!=self.last_fix:
      history=self.observer.tracker.history
      # Wait for the vehicle samples to bracket the original GPS time; do not
      # fabricate earlier motion or consume the raw GPS twice after rejection.
      if not history or history[-1].observed_at<anchor.observed_at:
        self.observation=Observation('waitingForMotionBracket');self.valid_until=0.
        return None
      self.last_fix=anchor.observed_at
      self.observer.today=self.today()
      self.observer.provider.version+=1  # New measured anchor may correct drift.
      self.observer.accept_fix(anchor,now=now,clock_uncertainty_s=item.anchor_uncertainty_ns/NS)
    result=self.observer.sample(now)
    road=self.observer.anchor_road
    e=result.estimate
    if e is None or road is None:
      self.observation=Observation(result.status);self.valid_until=0.
      return None
    self.valid_until=min(item.anchor_until_ns/NS,e.estimated_at+.15)
    if now>=self.valid_until:
      self.observation=Observation('motionExpired');return None
    context=replace(road.context,progress_m=result.progress_m,observed_at=e.estimated_at,
      motion_estimated=True,gps_observed_at=e.anchor_at,gps_uncertainty_s=e.anchor_clock_uncertainty_s,
      position_error_m=e.error_radius_m)
    result_road=replace(road,context=context)
    independent=self.observer.route_independent
    self.observation=Observation('currentRoadOnly' if independent else 'motionDerived',result_road,
      result.link_id,route_independent=independent)
    return result_road
