"""One-packet road command contract for the opt-in road control path.

No subscriptions, publishing sockets, Params or actuator APIs here. A caller must
explicitly opt in; unconfigured plannerd/controlsd keep the stock main target.
"""
from dataclasses import dataclass
import math
import time
from uuid import uuid4

from cereal import messaging

BASE_SOURCES = ('cruise', 'lead0', 'lead1', 'lead2', 'e2e')
LEASE = .15
TOLERANCE = 1e-5  # serialized Float32 comparison only, not a control tolerance


@dataclass(frozen=True)
class ResolvedCommand:
  decision_id: str
  acceleration: float
  should_stop: bool
  selected: bool
  source: str
  report: dict
  valid_until: float


def resolve(event, now, *, active=True, overridden=False):
  """Interpret the same coherent packet for the control consumer and its UI.

  None means the optional path cannot supply a command. An expired road event in
  a still-fresh plan falls back to that packet's own base output; an expired plan
  supplies nothing. This never extends either lifetime or changes engagement.
  """
  try:
    if event.which() != 'longitudinalPlan' or not event.valid or not active or overridden:
      return None
    p = event.longitudinalPlan
    r = p.roadConstraint.to_dict()
    stamp, model_at, until = event.logMonoTime/1e9, p.modelMonoTime/1e9, p.roadPlanValidUntil
    if (r.get('reportVersion') not in (2,3) or not r.get('planValid') or not r.get('enabled')
        or r.get('observationOnly') or not r.get('longitudinalActive') or r.get('overridden')):
      return None
    if (not p.roadDecisionId or len(p.roadDecisionId)>64 or not all(math.isfinite(v) for v in (now,stamp,model_at,until))
        or not 0 < model_at <= stamp+.01 or not -.01 <= now-stamp <= LEASE
        or not now < until <= min(stamp,model_at)+LEASE+.000001
        or not model_at-.01 <= r['plannedAt'] <= stamp+.01):
      return None
    base, chosen = r['baseAcceleration'], r['selectedAcceleration']
    # v3 keeps the ordinary aTarget/source intact. Old or disabled consumers
    # therefore see only the stock plan, even across mixed-version restarts.
    embedded = r['reportVersion'] == 3
    if (not all(math.isfinite(v) and abs(v)<=10 for v in (base,chosen,p.aTarget))
        or r['baseSource'] not in BASE_SOURCES or abs((base if embedded else chosen)-p.aTarget)>TOLERANCE
        or chosen>base+TOLERANCE or r['selected']!=(r['selectedSource']=='road')
        or str(p.longitudinalPlanSource)!=(r['baseSource'] if embedded else r['selectedSource'])):
      return None
    if r['selected']:
      if (p.shouldStop or not r['hasCandidate'] or not math.isfinite(r['candidateAcceleration'])
          or abs(r['candidateAcceleration']-chosen)>TOLERANCE):
        return None
      if r['status']=='constraint':
        if (not r['eventId'] or r['kind'] not in ('speedLimit','camera','curve','bump','section')
            or not math.isfinite(r['targetSpeed']) or not 0<r['targetSpeed']<=70
            or not math.isfinite(r['distance']) or abs(r['distance'])>10000
            or not math.isfinite(r['inputValidUntil']) or not 0<r['inputValidUntil']<=r['plannedAt']+.21):
          return None
      elif r['status']=='releasing':
        if r['eventId'] or r['kind'] or r['inputValidUntil']!=0:
          return None
      else:
        return None
    elif r['selectedSource']!=r['baseSource'] or abs(chosen-base)>TOLERANCE:
      return None
    if r['status'] in ('constraint','clear','approaching') and now>=r['inputValidUntil']:
      r.update(selected=False,selectedSource=r['baseSource'],selectedAcceleration=base,
        hasCandidate=False,candidateAcceleration=0.,status='invalid',rejection='inputExpired',
        eventId='',kind='',targetSpeed=0.,distance=0.,unreachable=False,inputValidUntil=0.)
    return ResolvedCommand(p.roadDecisionId,r['selectedAcceleration'],bool(p.shouldStop),r['selected'],
      r['selectedSource'],r,until)
  except (AttributeError,KeyError,ValueError,TypeError,OverflowError):
    return None


class CommandReader:
  """Latest packet ordering; repeated reads of the same plan are allowed at 100Hz.

  Different contents under an accepted ID/time, old packets and clock reversal
  revoke the optional output. This instance must live for the consumer session.
  """
  def __init__(self):
    self.stamp = self.now = -1.
    self.packet = None
    self.id = ''
    self.barrier = -1.
    self.blocked = False

  def read(self, packet, now, *, active=True, overridden=False):
    if not math.isfinite(now) or now<self.now:
      self.packet=None
      return None
    self.now=now
    if not active or overridden:
      self.packet=None
      self.barrier=now
      self.blocked=True
      return None
    if self.blocked:
      self.barrier=now
      self.blocked=False
    try:
      if len(packet)>65536:
        raise ValueError('packetTooLarge')
      with messaging.log.Event.from_bytes(packet,traversal_limit_in_words=8192) as event:
        stamp=event.logMonoTime
        identity=event.longitudinalPlan.roadDecisionId
        if stamp/1e9<self.barrier or stamp<self.stamp or (stamp==self.stamp and packet!=self.packet) or (identity==self.id and packet!=self.packet):
          self.packet=None
          return None
        result=resolve(event,now,active=active,overridden=overridden)
        if result is None:
          self.packet=None
          return None
        self.stamp,self.packet,self.id=stamp,packet,identity
        return result
    except Exception:
      self.packet=None
      return None


class RoadCommandBuilder:
  def __init__(self, adapter, *, clock=time.monotonic):
    self.adapter,self.clock=adapter,clock
    self.pending=None

  def prepare(self, base_event, planner, sm, *, previous_accel, enabled=False, embedded_only=False):
    # Default-off is exact byte passthrough, with no road polling or schema marker.
    self.pending=None
    if not enabled:
      self.adapter.observe_applied(False)
      return base_event.to_bytes()
    now=self.clock()
    if base_event.which()!='longitudinalPlan':
      raise ValueError('wrongBasePlan')
    original=base_event.longitudinalPlan
    if (abs(original.aTarget-float(planner.output_a_target))>TOLERANCE or original.shouldStop!=bool(planner.output_should_stop)
        or original.modelMonoTime!=sm.logMonoTime['modelV2']):
      self.adapter.observe_applied(False)
      raise ValueError('basePlanMismatch')
    decision=self.adapter.after_update(planner,sm,previous_accel=previous_accel,enabled=True)
    with messaging.log.Event.from_bytes(base_event.to_bytes()) as original_packet:
      packet=original_packet.as_builder()
    p=packet.longitudinalPlan
    stamp=base_event.logMonoTime/1e9
    until=min(stamp,original.modelMonoTime/1e9)+LEASE
    p.roadDecisionId=str(uuid4())
    p.roadPlanValidUntil=until
    if not embedded_only:
      p.aTarget=decision.acceleration
      p.longitudinalPlanSource='road' if decision.selected else decision.source
    valid=sm.all_checks(service_list=list(self.adapter.SERVICES)) and sm['carState'].canValid and planner.mpc.last_solve_status==0
    active=bool(valid and planner.CP.openpilotLongitudinalControl and sm['carControl'].longActive
      and str(sm['controlsState'].longControlState)!='off' and sm['carState'].vCruise!=255)
    overridden=bool(sm['carState'].brakePressed or sm['carState'].regenBraking or sm['carState'].brakeHoldActive or sm['carState'].gasPressed or sm['carControl'].cruiseControl.override)
    plan=decision.plan
    r=p.roadConstraint
    r.enabled=True;r.observationOnly=False;r.reportVersion=3 if embedded_only else 2
    r.planValid=valid;r.plannedAt=now;r.longitudinalActive=active;r.overridden=overridden
    r.status=plan.status;r.rejection=plan.rejection;r.eventId=plan.event_id;r.kind=plan.kind
    r.hasCandidate=plan.acceleration is not None
    r.candidateAcceleration=decision.acceleration if decision.selected else (plan.acceleration or 0.)
    r.selected=decision.selected;r.selectedSource='road' if decision.selected else decision.source
    r.selectedAcceleration=decision.acceleration
    r.baseAcceleration=float(planner.output_a_target)
    r.baseSource=str(original.longitudinalPlanSource)
    r.targetSpeed=plan.target_speed;r.distance=plan.distance;r.unreachable=plan.unreachable
    r.actionTime=planner.CP.longitudinalActuatorDelay+planner.dt
    r.inputValidUntil=getattr(self.adapter.source,'valid_until',0.) if plan.status in ('constraint','clear','approaching') else 0.
    data=packet.to_bytes()
    # Quantized transmitted acceleration is what acknowledgments must match.
    with messaging.log.Event.from_bytes(data) as emitted:
      result=resolve(emitted,self.clock())
    if result is None:
      self.adapter.observe_applied(False)
    else:
      self.pending=result
    return data

  def acknowledge(self, command, *, target_used=False):
    """Only current, actually consumed targets may seed next-cycle release.

    Call after the consumer uses this target in longitudinal PID. Merely sending
    or receiving a packet, stopping mode, an override or a replay is not feedback.
    """
    pending=self.pending
    if pending is not None and command is None:
      self.pending=None
      self.adapter.observe_applied(False)
      return False
    if pending is None or command is None or command.decision_id!=pending.decision_id:
      return False
    self.pending=None
    if self.clock()>=pending.valid_until:
      self.adapter.observe_applied(False)
      return False
    selected=bool(target_used and pending.selected and command.selected and
      abs(command.acceleration-pending.acceleration)<=TOLERANCE and self.clock()<command.valid_until)
    if selected and pending.report['status']=='constraint' and self.clock()>=pending.report['inputValidUntil']:
      selected=False
    self.adapter.observe_applied(selected)
    return selected
