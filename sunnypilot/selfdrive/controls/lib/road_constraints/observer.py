"""B1 road candidate observation. Never changes an actuator or stock planner output."""
import math
import time

from .planner import RoadConstraintPlanner, RoadPlan


class RoadObserver:
  def __init__(self, source=None, *, clock=time.monotonic):
    if source is None:
      from .ipc import RoadReader
      source = RoadReader(clock=clock)
    self.source, self.clock = source, clock
    self.planner = RoadConstraintPlanner()
    self.plan = RoadPlan()
    self.stamp = self.deadline = self.action_time = self.base_accel = 0.
    self.base_source = ''
    self.valid = self.active = self.overridden = False

  def update(self, sm, CP, dt, base_accel, base_source, ready):
    self.plan = RoadPlan(status='invalid', rejection='noInput')
    self.deadline = 0.
    self.stamp = self.clock()
    self.base_accel, self.base_source = base_accel, base_source
    self.valid = self.active = self.overridden = False
    try:
      self.valid = sm.all_checks(service_list=['carState', 'carControl', 'selfdriveState', 'modelV2'])
      self.active = bool(self.valid and ready and CP.openpilotLongitudinalControl and sm['carControl'].longActive)
      self.overridden = bool(sm['carState'].gasPressed or sm['carState'].brakePressed or sm['carControl'].cruiseControl.override)
      self.action_time = CP.longitudinalActuatorDelay + dt
      road = self.source(self.stamp)  # exactly one latest packet; no replay or wait
      self.plan = self.planner.update(road, now=self.stamp, v_ego=sm['carState'].vEgo, a_ego=sm['carState'].aEgo,
        previous_accel=base_accel, action_t=self.action_time, dt=dt, active=self.active, overridden=self.overridden)
      if road is not None and self.plan.status in ('constraint', 'clear', 'approaching'):
        limits = self.planner.validator.limits
        self.deadline = min(road.snapshot.source_at + limits.source_age, road.snapshot.received_at + limits.receive_age,
          road.context.observed_at + limits.context_age, getattr(self.source, 'valid_until', 0.))
        if not math.isfinite(self.deadline) or self.deadline <= self.clock():
          self.plan = RoadPlan(status='invalid', rejection='inputExpired')
          self.deadline = 0.
    except Exception:
      # An optional observer cannot interrupt the stock control loop.
      self.plan = RoadPlan(status='invalid', rejection='observerError')
      self.valid = False
    finally:
      # These hypothetical commands have never been applied to the car.
      self.planner.observe_selection(False)

  def publish(self, report):
    plan = self.plan
    if plan.acceleration is not None and self.clock() >= self.deadline:
      plan = RoadPlan(status='invalid', rejection='inputExpired')
    report.enabled = True
    report.observationOnly = True
    report.status, report.rejection = plan.status, plan.rejection
    report.eventId, report.kind = plan.event_id, plan.kind
    report.hasCandidate = plan.acceleration is not None
    report.candidateAcceleration = plan.acceleration if plan.acceleration is not None else 0.
    report.selected = False
    report.targetSpeed, report.distance, report.unreachable = plan.target_speed, plan.distance, plan.unreachable
    report.actionTime = self.action_time
    report.baseSource = report.selectedSource = self.base_source
    report.baseAcceleration = report.selectedAcceleration = self.base_accel
    report.reportVersion = 1
    report.planValid = self.valid
    report.plannedAt = self.stamp
    report.longitudinalActive, report.overridden = self.active, self.overridden
    report.inputValidUntil = self.deadline

  def close(self):
    self.source.close()
