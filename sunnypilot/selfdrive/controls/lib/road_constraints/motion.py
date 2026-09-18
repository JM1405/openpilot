"""Bounded vehicle-motion experiment; deliberately no RoadInput or IPC output.

GPS anchors keep their original mapped timestamps. Estimates name both clocks
and are never converted to fresh GPS measurements. Limits/error budgets below
are development assumptions, NOT measured sensor bounds or driving approval.
A live integration must separately bind authorization, clock mapping, publisher
leases, route changes and vehicle yaw sign. This module grants none of those.
"""
from collections import deque
from dataclasses import dataclass
import math

from .measurements import MOVING_SPEED, parse_measurements
from .offline import EARTH_M, Fix, angle_delta, distance

MAX_ANCHOR_AGE = 1.25
MAX_MOTION_GAP = .1
MAX_MOTION_AGE = .15
MAX_ERROR_M = 15.
SPEED_ERROR_MPS = .5
YAW_ERROR_RAD_S = .03
ACCEL_BOUND_MPS2 = 10.
EPS = 1e-8


def finite(value):
  return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True)
class MotionSample:
  observed_at: float  # Original vehicle sample time, same monotonic clock as GPS.
  speed_mps: float
  yaw_clockwise_rad_s: float  # Explicit convention; never assume a CAN yaw sign.
  valid: bool = True


@dataclass(frozen=True)
class MotionEstimate:
  anchor_at: float
  estimated_at: float  # Latest actual motion sample, NOT the poll time.
  anchor_clock_uncertainty_s: float
  lon: float
  lat: float
  bearing_deg: float
  speed_mps: float
  error_radius_m: float  # Assumed budget, not a confidence guarantee.
  heading_error_deg: float
  observation_only: bool = True


class MotionTracker:
  def __init__(self):
    self.history = deque(maxlen=512)
    self.last_now = -1.
    self.last_fix_at = -1.
    self.last_motion_at = -1.
    self.anchor = None
    self.clock_error = 0.
    self.confirmed = False
    self.status = 'waitingForMotion'

  def revoke(self, reason):
    """Revoke raw continuity on authorization/stream/dataset or motion failure.

    Route changes revoke road/path authority separately in MotionRoadObserver.
    """
    self.history.clear()
    self._invalidate(reason)
    # Keep replay watermarks. Clock/stream restart requires a new tracker.

  def _invalidate(self, reason):
    self.anchor = None
    self.confirmed = False
    self.status = reason

  def _clock(self, now):
    if not finite(now) or now < 0 or now < self.last_now:
      self.revoke('clockJump')
      return False
    self.last_now = now
    return True

  def push_motion(self, sample, *, now):
    if not self._clock(now):
      return False
    if (sample.valid is not True or not all(finite(v) for v in
        (sample.observed_at, sample.speed_mps, sample.yaw_clockwise_rad_s)) or
        sample.observed_at < 0 or not 0 <= now-sample.observed_at <= MAX_MOTION_AGE or
        not 0 <= sample.speed_mps <= 70 or abs(sample.yaw_clockwise_rad_s) > 1.2):
      self.revoke('invalidMotion')
      return False
    if sample.observed_at <= self.last_motion_at:
      self.revoke('motionReplay')
      return False
    self.last_motion_at = sample.observed_at
    if self.history:
      previous = self.history[-1]
      dt = sample.observed_at-previous.observed_at
      if dt <= 0:
        self.revoke('motionReplay')
        return False
      if dt > MAX_MOTION_GAP + EPS:
        self.revoke('motionGap')
      elif abs(sample.speed_mps-previous.speed_mps) > ACCEL_BOUND_MPS2*dt + .1:
        self.revoke('motionSpeedJump')
        return False
    self.history.append(sample)
    while len(self.history) > 2 and self.history[1].observed_at < sample.observed_at-2.:
      self.history.popleft()
    return True

  def _at(self, at):
    """Interpolate only between independently received vehicle samples."""
    if not self.history or not self.history[0].observed_at <= at <= self.history[-1].observed_at:
      return None
    before = self.history[0]
    for after in self.history:
      if after.observed_at == at:
        return after
      if after.observed_at > at:
        ratio = (at-before.observed_at)/(after.observed_at-before.observed_at)
        return MotionSample(at, before.speed_mps+(after.speed_mps-before.speed_mps)*ratio,
                            before.yaw_clockwise_rad_s+(after.yaw_clockwise_rad_s-before.yaw_clockwise_rad_s)*ratio)
      before = after
    return None

  def _project(self, anchor, uncertainty, end):
    first, last = self._at(anchor.observed_at), self._at(end)
    if first is None or last is None:
      return None
    age = end-anchor.observed_at
    if age < 0 or age+uncertainty > MAX_ANCHOR_AGE+EPS:
      return None
    points = [first]+[v for v in self.history if anchor.observed_at < v.observed_at < end]
    if end > first.observed_at:
      points.append(last)
    x = y = 0.
    heading = math.radians(anchor.bearing_deg)
    heading_error = math.radians(anchor.bearing_accuracy_deg)
    error = anchor.accuracy_m + (first.speed_mps+SPEED_ERROR_MPS)*uncertainty
    for a, b in zip(points, points[1:]):
      dt = b.observed_at-a.observed_at
      if dt > MAX_MOTION_GAP+EPS:
        return None
      travelled = .5*(a.speed_mps+b.speed_mps)*dt
      turn = .5*(a.yaw_clockwise_rad_s+b.yaw_clockwise_rad_s)*dt
      heading_error += YAW_ERROR_RAD_S*dt
      # Integrate in small motion intervals, including braking and curvature.
      x += travelled*math.sin(heading+turn/2)
      y += travelled*math.cos(heading+turn/2)
      heading += turn
      error += (SPEED_ERROR_MPS*dt + 2*travelled*math.sin(min(math.pi, heading_error)/2)
                + .5*ACCEL_BOUND_MPS2*dt*dt)
    if error > MAX_ERROR_M:
      return None
    lon = anchor.lon+math.degrees(x/(EARTH_M*math.cos(math.radians(anchor.lat))))
    lat = anchor.lat+math.degrees(y/EARTH_M)
    return MotionEstimate(anchor.observed_at, end, uncertainty, lon, lat,
                          math.degrees(heading)%360, last.speed_mps, error, math.degrees(heading_error))

  def accept_fix(self, fix: Fix, *, now, clock_uncertainty_s=0.):
    if not self._clock(now):
      return False
    if not finite(fix.observed_at) or fix.observed_at <= self.last_fix_at:
      self._invalidate('fixReplay')
      return False
    self.last_fix_at = fix.observed_at
    if (not finite(clock_uncertainty_s) or not 0 <= clock_uncertainty_s <= .052 or
        not 0 <= now-fix.observed_at or now-fix.observed_at+clock_uncertainty_s > .2+EPS):
      self._invalidate('staleOrUncertainFix')
      return False
    try:
      parse_measurements((fix.lon, fix.lat, fix.bearing_deg, fix.speed_mps, fix.accuracy_m, fix.bearing_accuracy_deg))
    except ValueError:
      self._invalidate('invalidFix')
      return False
    if fix.speed_mps < MOVING_SPEED:
      self._invalidate('stationaryFix')
      return False
    motion = self._at(fix.observed_at)
    if motion is None or now-self.history[-1].observed_at > MAX_MOTION_AGE:
      self._invalidate('missingMotionHistory')
      return False
    if abs(motion.speed_mps-fix.speed_mps) > 2.:
      self._invalidate('gpsVehicleSpeedMismatch')
      return False
    confirmed = False
    if self.anchor is not None:
      expected = self._project(self.anchor, self.clock_error, fix.observed_at)
      if expected is not None:
        if distance((fix.lon, fix.lat), (expected.lon, expected.lat)) > expected.error_radius_m+fix.accuracy_m+70*clock_uncertainty_s:
          self._invalidate('gpsMotionPositionMismatch')
          return False
        if angle_delta(fix.bearing_deg, expected.bearing_deg) > expected.heading_error_deg+fix.bearing_accuracy_deg+3.:
          self._invalidate('gpsMotionHeadingMismatch')
          return False
        confirmed = True
    self.anchor, self.clock_error, self.confirmed = fix, clock_uncertainty_s, confirmed
    self.status = 'motionEstimate' if confirmed else 'warmingUp'
    return True

  def estimate(self, now):
    if not self._clock(now):
      return None
    if self.anchor is None:
      return None
    if now-self.anchor.observed_at+self.clock_error > MAX_ANCHOR_AGE+EPS:
      self._invalidate('anchorExpired')
      return None
    if not self.history or now-self.history[-1].observed_at > MAX_MOTION_AGE:
      self._invalidate('motionExpired')
      return None
    if not self.confirmed:
      return None
    estimate = self._project(self.anchor, self.clock_error, self.history[-1].observed_at)
    if estimate is None:
      self._invalidate('motionBudgetExceeded')
      return None
    self.status = 'motionEstimate'
    return estimate
