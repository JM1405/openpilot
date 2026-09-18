"""Default-off selection adapter after the actual B1 planner update.

The optional control bridge uses this adapter. It returns a proposal; it does
not write planner outputs, publish control messages or change engagement state.
The caller must pass the command really used and acknowledge each application.
"""
import math
import time
from cereal import log
from openpilot.selfdrive.car.cruise import V_CRUISE_UNSET

from .planner import RoadPlan
from .selection import RoadCandidateSelector, RoadSelection


class PlannerRoadCandidate:
  SERVICES = ('carState', 'carControl', 'controlsState', 'selfdriveState', 'radarState', 'modelV2', 'liveParameters')

  def __init__(self, source, *, clock=time.monotonic):
    self.source, self.clock = source, clock
    self.selector = RoadCandidateSelector()

  def observe_applied(self, selected):
    self.selector.observe_applied(selected)

  def after_update(self, planner, sm, *, previous_accel, enabled=False):
    # Use the exact output and bounds finalized by LongitudinalPlanner.update,
    # including MPC/E2E arbitration, turn/throttle limits and bound smoothing.
    base = float(planner.output_a_target)
    stop = bool(planner.output_should_stop)
    source = next((name for name, value in log.LongitudinalPlan.LongitudinalPlanSource.schema.enumerants.items()
                   if value == planner.mpc.source), 'unknown')
    now = self.clock()
    try:
      if not math.isfinite(base):
        raise ValueError('invalidBaseOutput')
      ready = (str(sm['controlsState'].longControlState) != 'off' and sm['carState'].vCruise != V_CRUISE_UNSET)
      valid = sm.all_checks(service_list=list(self.SERVICES)) and sm['carState'].canValid and planner.mpc.last_solve_status == 0
      # LongControl's stopping state does not consume aTarget through its PID.
      # Keep the base stop plan and do not label an unused road target selected.
      active = bool(valid and ready and not stop and planner.CP.openpilotLongitudinalControl and sm['carControl'].longActive)
      overridden = bool(sm['carState'].brakePressed or sm['carState'].regenBraking or sm['carState'].brakeHoldActive or sm['carState'].gasPressed or sm['carControl'].cruiseControl.override)
      road = self.source(now) if enabled else None
      deadline = getattr(self.source, 'valid_until', 0.) if road is not None else 0.
      decision = self.selector.update(road, now=now, valid_until=deadline,
        v_ego=sm['carState'].vEgo, a_ego=sm['carState'].aEgo, previous_accel=previous_accel,
        base_accel=base, base_source=source, should_stop=stop, accel_bounds=planner.prev_accel_clip,
        action_t=planner.CP.longitudinalActuatorDelay+planner.dt, dt=planner.dt,
        active=active, overridden=overridden, valid_vehicle=valid, enabled=enabled)
      # Do not release a newly calculated event proposal after slow source/math
      # work has exhausted its original lease. Its old event metadata is dropped.
      if decision.selected and decision.plan.status == 'constraint' and self.clock() >= deadline:
        self.selector.observe_applied(False)
        return RoadSelection(base, source, stop, plan=RoadPlan(status='invalid', rejection='candidateExpired'))
      return decision
    except Exception:
      self.selector.observe_applied(False)
      self.selector.planner.was_active = False
      return RoadSelection(base, source, stop, plan=RoadPlan(status='invalid', rejection='plannerCandidateError'))
