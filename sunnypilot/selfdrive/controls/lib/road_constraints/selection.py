"""Default-disabled road acceleration selection candidate for desktop rehearsal.

No runtime imports this module. No sockets, Params, actuator writes or engagement
changes. A future integration must supply the finalized base command, its current
bounds and the actual previous command, then acknowledge whether this proposal
was used. Merely computing a proposal must never seed a release transition.
"""
from dataclasses import dataclass, replace
import math

from .planner import RoadConstraintPlanner, RoadPlan, clip


@dataclass(frozen=True)
class RoadSelection:
  acceleration: float
  source: str
  should_stop: bool
  selected: bool = False
  plan: RoadPlan = RoadPlan()


class RoadCandidateSelector:
  def __init__(self):
    self.planner = RoadConstraintPlanner()
    self.last_time = None
    self.proposed = False

  def observe_applied(self, selected: bool):
    # The caller must acknowledge each cycle; a proposal alone is not feedback.
    self.planner.observe_selection(bool(selected and self.proposed))
    self.proposed = False

  def update(self, road, *, now, valid_until, v_ego, a_ego, previous_accel,
             base_accel, base_source, should_stop, accel_bounds, action_t, dt,
             active, overridden=False, valid_vehicle=True, enabled=False):
    if not math.isfinite(base_accel):
      # There is no valid base output to preserve. Do not manufacture a command.
      raise ValueError('nonfiniteBaseAcceleration')
    base = RoadSelection(base_accel, base_source, should_stop)
    self.proposed = False
    reason = ''
    if not enabled:
      reason = 'disabled'
    elif not valid_vehicle:
      reason = 'invalidVehicleState'
    elif (not math.isfinite(now) or now < 0 or
          (self.last_time is not None and not 0 < now - self.last_time <= .2)):
      reason = 'plannerClockGap'
    elif (len(accel_bounds) != 2 or not all(math.isfinite(x) for x in accel_bounds)
          or not -10 <= accel_bounds[0] <= accel_bounds[1] <= 10):
      reason = 'invalidAccelerationBounds'
    self.last_time = now if math.isfinite(now) and now >= 0 else None
    if reason:
      self.planner.was_active = False
      self.planner.observe_selection(False)
      return replace(base, plan=RoadPlan(status='disabled' if reason == 'disabled' else 'invalid', rejection=reason))

    # Preserve the shortest GPS/IPC/route lease supplied by RoadReader; never
    # substitute a new receipt timestamp for the validity of the underlying input.
    expired = road is not None and (not math.isfinite(valid_until) or now >= valid_until)
    try:
      plan = self.planner.update(None if expired else road, now=now, v_ego=v_ego, a_ego=a_ego,
        previous_accel=previous_accel, action_t=action_t, dt=dt, active=active, overridden=overridden)
    except Exception:
      self.planner.was_active = False
      plan = RoadPlan(status='invalid', rejection='candidateError')
    finally:
      # Consume last cycle's acknowledgment even when the caller skips this one.
      self.planner.observe_selection(False)
    if expired and plan.rejection == 'noInput':
      plan = replace(plan, rejection='inputExpired')
    if plan.acceleration is None:
      return replace(base, plan=plan)

    candidate = float(clip(plan.acceleration, *accel_bounds))
    if not math.isfinite(candidate):
      return replace(base, plan=RoadPlan(status='invalid', rejection='nonfiniteCandidate'))
    # Stronger lead/E2E braking always wins, even outside the optional road
    # envelope. A road candidate cannot raise the finalized stock acceleration.
    selected = candidate < base_accel
    self.proposed = selected
    return RoadSelection(candidate if selected else base_accel,
      ('roadRelease' if plan.status == 'releasing' else 'roadConstraint') if selected else base_source,
      should_stop, selected, plan)
