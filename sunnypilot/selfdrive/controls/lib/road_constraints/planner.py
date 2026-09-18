from dataclasses import dataclass, replace
import math

from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.contract import RoadInput, RoadInputValidator


def clip(value: float, low: float, high: float) -> float:
  return min(high, max(low, value))


@dataclass(frozen=True)
class RoadLimits:
  # Development envelope, not a calibrated vehicle comfort profile.
  min_accel: float = -1.5
  max_accel: float = 2.0
  jerk: float = 0.8
  margin_m: float = 2.0
  margin_seconds: float = 0.5
  # Reserve braking authority and response time in predictions. These are local
  # development assumptions, not measured Ioniq5 actuator parameters.
  braking_factor: float = 0.8
  delay_margin: float = 0.2

  def __post_init__(self):
    values = (self.min_accel, self.max_accel, self.jerk, self.margin_m, self.margin_seconds, self.braking_factor, self.delay_margin)
    if not all(math.isfinite(x) for x in values):
      raise ValueError("Road limits must be finite")
    if (self.min_accel >= 0 or self.max_accel <= 0 or self.jerk <= 0 or min(self.margin_m, self.margin_seconds, self.delay_margin) < 0
        or not 0 < self.braking_factor <= 1):
      raise ValueError("Invalid road planning envelope")


@dataclass(frozen=True)
class RoadPlan:
  acceleration: float | None = None
  status: str = "disabled"
  rejection: str = ""
  event_id: str = ""
  kind: str = ""
  target_speed: float = 0.0
  distance: float = 0.0
  unreachable: bool = False


def advance(v: float, a: float, jerk: float, duration: float) -> tuple[float, float]:
  """Constant-jerk kinematics, truncated at standstill; returns distance and speed.

  Same SI kinematics used by Sunny's map controller, isolated from its Params,
  coordinates and speed-target state machine. Never integrate backwards motion.
  """
  roots = []
  if abs(jerk) > 1e-9:
    discriminant = a * a - 2.0 * jerk * v
    if discriminant >= 0:
      roots = [(-a - math.sqrt(discriminant)) / jerk, (-a + math.sqrt(discriminant)) / jerk]
  elif a < 0:
    roots = [-v / a]
  if v == 0 and (a < 0 or (a == 0 and jerk <= 0)):
    return 0.0, 0.0
  duration = min([duration] + [t for t in roots if 0 < t < duration])
  return max(0.0, v * duration + a * duration**2 / 2 + jerk * duration**3 / 6), max(0.0, v + a * duration + jerk * duration**2 / 2)


def braking_distance(v: float, a: float, target: float, limits: RoadLimits) -> float:
  """Distance needed to reach target on a jerk-limited ramp/hold/release.

  Solves the triangular peak first, then adds a constant-deceleration plateau if
  needed. If releasing the current brake already undershoots target, count only
  to the first target crossing. Counting the below-target tail can reject a
  feasible release and incorrectly keep maximum braking until below target.
  An already stronger lead brake is released, not clipped away. This is
  a longitudinal kinematic envelope, not a tire/grade/actuator dynamics model.
  """
  j = limits.jerk
  if v + max(a, 0.0)**2 / (2 * j) <= target:
    return 0.0
  if a < 0 and v - a * a / (2 * j) <= target:
    # Already braking enough: measure only to first reaching the target. The
    # remainder of the release runs below it and need not fit before the point.
    time_to_target = 2 * (v - target) / (-a + math.sqrt(max(0.0, a * a - 2 * j * (v - target))))
    return advance(v, a, j, time_to_target)[0]
  peak = max(-a, min(-limits.min_accel, math.sqrt(max(0.0, j * (v - target) + a * a / 2))))
  down_time = max(0.0, (a + peak) / j)
  distance, speed = advance(v, a, -j, down_time)
  hold_time = max(0.0, (speed - target - peak * peak / (2 * j)) / peak) if peak > 0 else 0.0
  dx, speed = advance(speed, -peak, 0.0, hold_time)
  distance += dx
  dx, _ = advance(speed, -peak, j, peak / j)
  return distance + dx


class RoadConstraintPlanner:
  def __init__(self, limits: RoadLimits | None = None):
    self.limits = limits or RoadLimits()
    self.validator = RoadInputValidator()
    self.was_selected = False
    self.was_active = False

  def observe_selection(self, selected: bool) -> None:
    # Only the actual final winner may seed a release transition.
    self.was_selected = selected

  def _clear(self, status: str, rejection: str, previous_accel: float, dt: float) -> RoadPlan:
    if self.was_selected:
      # No old event metadata survives invalidation/removal. This ceiling only
      # limits upward recovery; it never delays a stronger lead/E2E brake.
      return RoadPlan(min(self.limits.max_accel, previous_accel + self.limits.jerk * dt), "releasing", rejection)
    return RoadPlan(status=status, rejection=rejection)

  def update(self, road_input: RoadInput | None, *, now: float, v_ego: float, a_ego: float,
             previous_accel: float, action_t: float, dt: float, active: bool, overridden: bool = False) -> RoadPlan:
    if not all(math.isfinite(x) for x in (now, v_ego, a_ego, previous_accel, action_t, dt)):
      self.was_selected = False
      self.was_active = False
      return RoadPlan(status="invalid", rejection="invalidVehicleState")
    if not 0 <= v_ego <= 70 or not 0 < dt <= 0.2 or not dt <= action_t <= 1.0 or max(abs(a_ego), abs(previous_accel)) > 10:
      self.was_selected = False
      self.was_active = False
      return RoadPlan(status="invalid", rejection="invalidVehicleState")
    if not active or overridden:
      self.was_selected = False
      self.was_active = False
      return RoadPlan(status="overridden" if overridden else "inactive")
    if not self.was_active:
      # Outputs computed while disengaged/overridden were not applied to the car.
      # Resume from measured acceleration, not those hypothetical commands.
      previous_accel = a_ego
    self.was_active = True
    rejection = self.validator.validate(road_input, now)
    if rejection:
      return self._clear("invalid", rejection, previous_accel, dt)

    s, c = road_input.snapshot, road_input.context
    # Project only a validated, fresh path position to now. With current speed
    # and acceleration, the distance since the sample is v_now*t - a_now*t²/2.
    # This cannot refresh an expired timestamp or repair an unconfirmed path.
    age = max(0.0, now - c.observed_at)
    progress = c.progress_m - s.reference_progress_m + max(0.0, v_ego * age - a_ego * age * age / 2)
    uncertainty = c.position_error_m if c.motion_estimated else 0.
    # Brake for the nearest plausible target, but keep it until even the
    # farthest plausible vehicle position has passed. Do not skip a camera
    # merely because an estimate's forward error overlaps its target point.
    remaining = [event for event in s.constraints if event.end_m >= progress-uncertainty]
    if not remaining:
      return self._clear("clear", "", previous_accel, dt)

    limits = self.limits
    planning_limits = replace(limits, min_accel=limits.min_accel * limits.braking_factor, jerk=limits.jerk * limits.braking_factor)
    horizon = action_t + limits.delay_margin
    candidates = []
    any_unreachable = False
    for event in remaining:
      distance = event.start_m - progress - uncertainty
      target = event.target_speed
      available = max(0.0, distance - limits.margin_m - target * limits.margin_seconds)

      def feasible(accel: float, available: float = available, target: float = target) -> bool:
        # The candidate remains an acceleration command. Predict its effect
        # with reserved braking authority and extra response time, starting
        # from measured acceleration. The final command bounds/slew and the
        # main planner's lead/E2E candidates are unchanged.
        accel *= limits.braking_factor if accel < 0 else 1.0
        dx, speed = advance(v_ego, a_ego, (accel - a_ego) / horizon, horizon)
        if available == 0:
          # Speed servo inside the segment/arrival buffer, including the speed
          # change required to release this acceleration with bounded jerk.
          settled_speed = speed + accel * abs(accel) / (2 * planning_limits.jerk)
          return settled_speed <= target
        if dx >= available:
          # A horizon can cross the target while already travelling below it.
          # Remaining distance alone must not trigger braking again in that case.
          return speed + max(accel, 0.0)**2 / (2 * planning_limits.jerk) <= target
        return dx + braking_distance(speed, accel, target, planning_limits) <= available

      low, high = limits.min_accel, limits.max_accel
      unreachable = not feasible(low)
      any_unreachable |= unreachable
      if feasible(high):
        continue
      if unreachable:
        high = low
      else:
        for _ in range(24):
          mid = (low + high) / 2
          if feasible(mid):
            low = mid
          else:
            high = mid
        high = low
      candidates.append(RoadPlan(high, "constraint", "", event.event_id, event.kind.value, target, distance, unreachable))

    if not candidates:
      return self._clear("approaching", "", previous_accel, dt)
    plan = min(candidates, key=lambda candidate: candidate.acceleration)
    # Select the binding event before limiting slew: otherwise several events
    # collapse to the same limited value and the reported cause depends on order.
    # Limit only this road candidate, never the final lead/E2E/cruise output.
    acceleration = clip(plan.acceleration, previous_accel - limits.jerk * dt, previous_accel + limits.jerk * dt)
    # A non-winning event may still be unreachable; do not hide that condition.
    return RoadPlan(acceleration, plan.status, plan.rejection, plan.event_id, plan.kind,
                    plan.target_speed, plan.distance, any_unreachable)
