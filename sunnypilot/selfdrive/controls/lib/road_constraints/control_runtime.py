"""Opt-in plannerd/controlsd bridge. Legacy main targets always remain stock.

v3 embeds the optional target; only this validating consumer can use it. No
activation, Params mutation or engagement decisions are made by this module.
"""
from dataclasses import replace
import math
import time
from cereal import car, messaging
from .command import CommandReader, RoadCommandBuilder, ResolvedCommand, BASE_SOURCES, TOLERANCE, LEASE, resolve
from .planner_candidate import PlannerRoadCandidate
from .runtime import control_enabled


class PlannerControlBridge:
  def __init__(self, source=None, *, clock=time.monotonic):
    if source is None:
      from .ipc import RoadReader
      source=RoadReader(clock=clock)
    self.clock=clock
    self.builder=RoadCommandBuilder(PlannerRoadCandidate(source,clock=clock),clock=clock)
    self.source=source
    self.plan_stamp=0

  def publish(self, planner, sm, pm):
    # An actual previous control target is useful only while its containing
    # controlsState and original plan are still current and from our decision.
    previous=float(planner.output_a_target)
    pending=self.builder.pending
    try:
      fb=sm['controlsState'].roadControl
      at=self.clock();stamp=sm.logMonoTime['controlsState']/1e9
      valid=(sm.all_checks(['controlsState','carState','carControl']) and sm['carState'].canValid
        and 0 <= at-stamp <= LEASE and fb.version==1 and pending is not None
        and fb.decisionId==pending.decision_id and fb.planMonoTime==self.plan_stamp
        and self.plan_stamp/1e9 <= stamp and at < fb.validUntil <= pending.valid_until
        and math.isfinite(fb.aTarget) and abs(fb.aTarget)<=10
        and str(sm['controlsState'].longControlState)=='pid' and fb.targetUsed)
      if valid:
        receipt=feedback_command(fb,at)
        adjusted=(fb.consumerLimited and receipt is not None and receipt.report['status']=='releasing'
          and abs(receipt.report['baseAcceleration']-pending.report['baseAcceleration'])<=TOLERANCE
          and fb.aTarget<=pending.acceleration+TOLERANCE)
        if adjusted:
          # The consumer owns recovery; do not acknowledge a different target as
          # the planner's winner. Still seed the next proposal from actual use.
          self.builder.acknowledge(None)
          previous=float(fb.aTarget)
        else:
          command=replace(pending,acceleration=fb.aTarget,selected=bool(fb.selected))
          self.builder.acknowledge(command,target_used=True)
          if not fb.consumerLimited and abs(fb.aTarget-(pending.acceleration if fb.selected else pending.report['baseAcceleration']))<=TOLERANCE:
            previous=float(fb.aTarget)
      else:
        self.builder.acknowledge(None)
    except (AttributeError,ValueError,TypeError):
      self.builder.acknowledge(None)

    bridge=self
    class Destination:
      def send(self, name, packet):
        if name=='longitudinalPlan':
          try:
            data=bridge.builder.prepare(packet,planner,sm,previous_accel=previous,enabled=True,embedded_only=True)
          except Exception:
            # Failure in an optional adapter cannot suppress the stock plan.
            bridge.builder.pending=None
            bridge.builder.adapter.observe_applied(False)
            data=packet.to_bytes()
          bridge.plan_stamp=packet.logMonoTime
          pm.send(name,data)
        else:
          pm.send(name,packet)
    planner.publish(sm,Destination())

  def close(self):
    self.source.close()


def create_control_bridge():
  if not control_enabled():
    return None
  try:
    return PlannerControlBridge()
  except Exception:
    # A missing optional transport must not prevent stock plannerd startup.
    return None


class RoadControlConsumer:
  def __init__(self, *, enabled=None, clock=time.monotonic):
    self.enabled=control_enabled() if enabled is None else enabled
    self.clock=clock;self.reader=CommandReader()
    self.command=None;self.plan_stamp=0;self.used=False
    self.target=0.;self.stop=False
    self.applied=None
    self.consumer_limited=False

  def target_for(self, sm, *, active, overridden=False, vehicle_valid=True):
    plan=sm['longitudinalPlan']
    self.command=None;self.used=False;self.consumer_limited=False
    self.target,self.stop=float(plan.aTarget),bool(plan.shouldStop)
    if not self.enabled:
      self.applied=None
      return self.target,self.stop
    now=self.clock()
    try:
      valid=vehicle_valid and sm.all_checks(['longitudinalPlan','carState','selfdriveState','onroadEvents']) and sm['carState'].canValid
      stamp=sm.logMonoTime['longitudinalPlan']
      # Always copy the received plan. Mutated same-stamp payloads reach the
      # ordering guard instead of being hidden by a timestamp-only cache.
      event=messaging.new_message('longitudinalPlan',valid=bool(valid),logMonoTime=stamp)
      event.longitudinalPlan=plan
      if plan.roadConstraint.reportVersion==3:
        command=self.reader.read(event.to_bytes(),now,active=bool(active and valid),overridden=overridden)
      else:
        self.reader.read(b'',now,active=bool(active and valid),overridden=overridden)
        command=None
      if command is not None:
        self.command=command;self.plan_stamp=stamp
        self.target,self.stop=command.acceleration,command.should_stop
      # Recovery is an actuator transition, not permission to retain a road
      # event. It needs a fresh ordinary plan and current driver/vehicle gates.
      model_at=plan.modelMonoTime/1e9
      base_source=str(plan.longitudinalPlanSource)
      fresh_base=(valid and active and not overridden and not self.stop
        and math.isfinite(self.target) and abs(self.target)<=10
        and base_source in BASE_SOURCES and 0<model_at<=stamp/1e9+.01
        and -.01<=now-stamp/1e9<=LEASE and now<min(stamp/1e9,model_at)+LEASE)
      if not fresh_base:
        self.applied=None
      elif self.applied is not None:
        previous,at=self.applied
        dt=now-at
        if not 0<=dt<=LEASE:
          self.applied=None
        else:
          ceiling=previous+.8*dt
          if self.target>ceiling+TOLERANCE:
            self.target=ceiling;self.consumer_limited=True;self.plan_stamp=stamp
            # Use only this current plan's base target/lease. Old event identity,
            # target speed, distance and input authority are never copied.
            report=dict(reportVersion=3,enabled=True,observationOnly=False,planValid=True,
              plannedAt=stamp/1e9,longitudinalActive=True,overridden=False,status='releasing',
              rejection='consumerRecovery',eventId='',kind='',hasCandidate=True,
              candidateAcceleration=ceiling,selected=True,selectedSource='road',selectedAcceleration=ceiling,
              baseAcceleration=float(plan.aTarget),baseSource=base_source,targetSpeed=0.,distance=0.,
              unreachable=False,inputValidUntil=0.)
            self.command=ResolvedCommand(plan.roadDecisionId or 'consumer-release:'+str(stamp),ceiling,
              False,True,'road',report,min(stamp/1e9,model_at)+LEASE)
    except Exception:
      self.reader.read(b'',now,active=False)
      self.applied=None
    return self.target,self.stop

  def observe_pid(self, state, *, active):
    self.used=bool(self.command is not None and active and state==car.CarControl.Actuators.LongControlState.pid)
    # A proposal or a stopping/starting output cannot seed a recovery ceiling.
    self.applied=(self.target,self.clock()) if self.used and self.command.selected else None

  def write_feedback(self, feedback):
    if not self.enabled:
      return
    feedback.version=1
    feedback.consumerLimited=self.consumer_limited
    command=self.command
    if command is None:
      return
    feedback.decisionId=command.decision_id;feedback.planMonoTime=self.plan_stamp
    feedback.aTarget=self.target;feedback.shouldStop=self.stop
    feedback.targetUsed=self.used;feedback.selected=bool(self.used and command.selected)
    feedback.validUntil=command.valid_until;feedback.report=command.report


def feedback_command(feedback, now):
  """Revalidate one consumer receipt for UI, without joining a newer plan."""
  try:
    if feedback.version!=1 or not feedback.decisionId or (not feedback.targetUsed and not feedback.shouldStop):
      return None
    r=feedback.report
    if r.reportVersion!=3 or feedback.selected!=bool(feedback.targetUsed and r.selected):
      return None
    event=messaging.new_message('longitudinalPlan',valid=True,logMonoTime=feedback.planMonoTime)
    p=event.longitudinalPlan
    # Recover the original model limit from validUntil, which the producer
    # bounded by its model timestamp. Do not renew at the consumer's receipt.
    p.modelMonoTime=int((feedback.validUntil-LEASE)*1e9)
    p.roadDecisionId=feedback.decisionId;p.roadPlanValidUntil=feedback.validUntil
    p.aTarget=r.baseAcceleration;p.longitudinalPlanSource=r.baseSource
    p.shouldStop=feedback.shouldStop;p.roadConstraint=r
    command=resolve(event,now)
    if command is None or abs(command.acceleration-feedback.aTarget)>TOLERANCE or command.selected!=feedback.selected:
      return None
    return command
  except (AttributeError,ValueError,TypeError):
    return None
