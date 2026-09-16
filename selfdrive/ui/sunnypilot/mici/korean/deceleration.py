"""Read-only explanation of one main-planner decision, not measured braking.

The road report carries the final winner, actuator target and original input
deadline together. Never join its event metadata to a different plan message.
"""
from dataclasses import dataclass
import math

LEASE = .15
KINDS = {'speedLimit': '제한속도', 'camera': '단속 지점', 'section': '구간 단속', 'bump': '방지턱', 'curve': '커브'}
SOURCES = {'lead0': '앞차', 'lead1': '앞차', 'lead2': '앞차', 'e2e': '모델', 'cruise': '속도'}


@dataclass(frozen=True)
class DecelerationStatus:
  state: str
  title: str
  detail: str = ''
  selected: bool = False


WAITING = DecelerationStatus('waiting', '감속 상태 확인 대기')


def recent(stamp, now):
  return math.isfinite(stamp) and stamp > 0 and -.01 <= now - stamp <= LEASE


def explain(report, now, *, metric=True):
  """Validated transport and live driver gates are checked by DecelerationMonitor."""
  if (report.reportVersion != 1 or not report.planValid or not recent(report.plannedAt, now)
      or not math.isfinite(report.selectedAcceleration) or abs(report.selectedAcceleration) > 10):
    return WAITING
  if not report.enabled:
    return DecelerationStatus('disabled', '도로 감속 꺼짐')
  if not report.longitudinalActive or report.overridden:
    return WAITING  # the latest live state and this decision have not caught up
  source = report.selectedSource
  if report.selected != (source == 'road') or source not in (*SOURCES, 'road'):
    return WAITING
  if report.hasCandidate and (not math.isfinite(report.candidateAcceleration) or abs(report.candidateAcceleration) > 10):
    return WAITING
  input_fresh = (report.status in ('constraint', 'clear', 'approaching') and math.isfinite(report.inputValidUntil)
                 and now < report.inputValidUntil <= report.plannedAt + .21)
  candidate = report.hasCandidate and report.status == 'constraint' and input_fresh
  if source == 'road':
    if not report.hasCandidate:
      return WAITING
    if report.status == 'releasing':
      return DecelerationStatus('releasing', '도로 감속 해제 중', '새 도로 입력 확인 대기')
    if not candidate:
      return DecelerationStatus('expired', '도로 입력 확인 대기')
    if (report.kind not in KINDS or not report.eventId or not math.isfinite(report.targetSpeed)
        or not 0 <= report.targetSpeed <= 70 or not math.isfinite(report.distance) or abs(report.distance) > 10000):
      return WAITING
    speed = round(report.targetSpeed * (3.6 if metric else 2.236936))
    unit = 'km/h' if metric else 'mph'
    distance = max(0, report.distance)
    location = (f'약 {round(distance):d} m' if metric else f'약 {round(distance * 3.28084):d} ft') if distance > 0 else '구간 안'
    detail = f'목표 {speed} {unit} / {location}'
    if report.unreachable:
      detail = '목표 감속 여유 부족'
    if report.selectedAcceleration < -.01:
      return DecelerationStatus('road', KINDS[report.kind] + ' 감속 계획', detail, True)
    return DecelerationStatus('limiting', KINDS[report.kind] + ' 가속 제한', detail)
  detail = '도로 후보 대기' if candidate else ('도로 입력 확인됨' if input_fresh else '도로 입력 확인 대기')
  if report.selectedAcceleration < -.01:
    # E2E does not explain whether it saw a bend, signal, crossing or another cause.
    return DecelerationStatus('base', SOURCES[source] + ' 감속 계획', detail, True)
  return DecelerationStatus('candidate' if candidate else 'ready', '도로 후보 대기' if candidate else '감속 계획 없음',
                            '' if candidate else detail)


class DecelerationMonitor:
  def __init__(self):
    self.drive = None
    self.received = {}
    self.high_water = {}
    self.accepted = {}
    self.control_barrier = 0.0
    self.driver_blocked = False

  def _message(self, sm, name, now, started_frame, started_time):
    if name not in sm.services or not sm.seen[name]:
      self.accepted[name] = False
      return None
    frame, stamp = sm.recv_frame[name], sm.logMonoTime[name] / 1e9
    signature = (frame, stamp, bool(sm.valid[name]))
    if self.received.get(name) != signature:
      old = self.high_water.get(name, 0)
      self.accepted[name] = (sm.valid[name] and frame >= started_frame and stamp >= started_time
                             and recent(stamp, now) and recent(sm.recv_time[name], now) and stamp > old)
      if name == 'longitudinalPlanSP':
        planned = sm[name].roadConstraint.plannedAt
        self.accepted[name] = (self.accepted[name] and math.isfinite(planned)
                               and self.high_water.get('decision', 0) < planned <= stamp + .01)
        if recent(planned, now) and planned <= stamp + .01:
          self.high_water['decision'] = max(self.high_water.get('decision', 0), planned)
      if recent(stamp, now):
        self.high_water[name] = max(old, stamp)
      self.received[name] = signature
    if not self.accepted.get(name) or not recent(stamp, now) or not recent(sm.recv_time[name], now):
      return None
    return sm[name]

  def _driver_hold(self, status, now):
    self.control_barrier, self.driver_blocked = now, True
    return status

  def update(self, sm, now, *, started_frame, started_time, openpilot_longitudinal, metric=True, driving_active=None):
    if not math.isfinite(now):
      return WAITING
    drive = (started_frame, started_time)
    if drive != self.drive:
      self.__init__()
      self.drive = drive
    messages = {name: self._message(sm, name, now, started_frame, started_time)
                for name in ('carControl', 'carState', 'controlsState', 'longitudinalPlanSP')}
    if driving_active is False:
      return self._driver_hold(WAITING, now)
    cc, cs, controls = (messages[name] for name in ('carControl', 'carState', 'controlsState'))
    if any(item is None for item in (cc, cs, controls)) or not cs.canValid:
      return self._driver_hold(WAITING, now)
    if openpilot_longitudinal is None:
      return self._driver_hold(WAITING, now)
    if not openpilot_longitudinal:
      return self._driver_hold(DecelerationStatus('stock', '속도 보조 꺼짐'), now)
    if cs.brakePressed or not cc.longActive or controls.longControlState == 'off':
      return self._driver_hold(DecelerationStatus('inactive', '속도 보조 해제'), now)
    if cs.gasPressed or cc.cruiseControl.override:
      return self._driver_hold(DecelerationStatus('overridden', '운전자 속도 조절 중'), now)
    if self.driver_blocked:
      self.control_barrier = max(self.control_barrier, *(sm.logMonoTime[name] / 1e9 for name in ('carControl', 'carState', 'controlsState')))
      self.driver_blocked = False
    plan = messages['longitudinalPlanSP']
    if plan is None or plan.roadConstraint.plannedAt < max(started_time, self.control_barrier):
      return WAITING
    return explain(plan.roadConstraint, now, metric=metric)
