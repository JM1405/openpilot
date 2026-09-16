"""Read-only driving state shared by the MICI HUD and settings page.

Buttons request engagement; this presenter never certifies that it will succeed.
No Params writes, carControl publications, or remembered speed estimates.
"""
from dataclasses import dataclass
import math
import os

FAST_LEASE = .15
EVENT_LEASE = 1.2  # onroadEvents is sent on changes and once per second


def enabled():
  return os.getenv('KOREAN_DRIVING_STATUS', '0') == '1' or os.getenv('KOREAN_ROAD_INPUT', '0') == '1'


@dataclass(frozen=True)
class DrivingStatus:
  state: str
  title: str
  detail: str = ''
  set_speed_kph: float | None = None
  speed_label: str = '설정속도'
  lateral: bool | None = None
  action: str = ''

  def speed_text(self, metric=True):
    if self.set_speed_kph is None:
      return '미설정' if self.state == 'ready' else '확인 대기'
    speed = self.set_speed_kph * (1 if metric else .621371)
    return f'{round(speed)} ' + ('km/h' if metric else 'mph')

  @property
  def steering_text(self):
    return '조향 상태 확인 대기' if self.lateral is None else '조향 보조 중' if self.lateral else '조향 보조 꺼짐'


WAITING = DrivingStatus('waiting', '주행 상태 확인 대기', '최근 상태를 기다리는 중')
OFFROAD = DrivingStatus('offroad', '주행 전', '시동 후 주행 상태 확인')


class DrivingStatusMonitor:
  def __init__(self):
    self.drive = None
    self.received = {}
    self.high_water = {}
    self.accepted = {}

  def _message(self, sm, name, now, start_frame, start_time, lease):
    def fresh(stamp):
      return math.isfinite(stamp) and stamp > 0 and -.01 <= now - stamp <= lease

    if name not in sm.services or not sm.seen[name]:
      self.accepted[name] = False
      return None
    frame, stamp = sm.recv_frame[name], sm.logMonoTime[name] / 1e9
    received = sm.recv_time[name]
    signature = (frame, stamp, bool(sm.valid[name]))
    if self.received.get(name) != signature:
      old = self.high_water.get(name, 0.)
      self.accepted[name] = (sm.valid[name] and frame >= start_frame and stamp >= start_time and
                             fresh(stamp) and fresh(received) and stamp > old)
      if fresh(stamp):
        self.high_water[name] = max(old, stamp)
      self.received[name] = signature
    if not self.accepted.get(name) or not fresh(stamp) or not fresh(received):
      return None
    return sm[name]

  def update(self, sm, now, *, started, started_frame, started_time, CP):
    drive = (started, started_frame, started_time)
    if drive != self.drive:
      self.__init__()
      self.drive = drive
    if not started:
      return OFFROAD
    if not math.isfinite(now) or CP is None:
      return WAITING
    messages = {name: self._message(sm, name, now, started_frame, started_time, FAST_LEASE)
                for name in ('carState', 'carControl', 'selfdriveState')}
    cs, cc, ss = (messages[name] for name in ('carState', 'carControl', 'selfdriveState'))
    events = self._message(sm, 'onroadEvents', now, started_frame, started_time, EVENT_LEASE)
    if any(item is None for item in (cs, cc, ss)) or not cs.canValid or cs.canTimeout:
      return WAITING
    if CP.passive:
      return DrivingStatus('passive', '주행 보조 꺼짐', '주행 보조 사용 불가')
    if not CP.openpilotLongitudinalControl or CP.pcmCruise:
      return DrivingStatus('stock', '차량 크루즈 상태', '차량 계기판에서 확인', lateral=bool(cc.latActive))

    speed = cs.vCruiseCluster if cs.vCruiseCluster != 0 else cs.vCruise
    if not math.isfinite(speed) or speed < 0 or speed > 255:
      return WAITING
    speed = float(speed) if 0 < speed < 255 else None
    saved = {'set_speed_kph': speed, 'lateral': bool(cc.latActive)}
    # MADS can strip some main events. Combine live pedals/vehicle gates with
    # both main state and the published event list before suggesting a request.
    blocking = (events is None or any(e.noEntry or e.immediateDisable or e.softDisable for e in events) or
                not ss.engageable or not cs.cruiseState.available or cs.gearShifter != 'drive' or
                cs.doorOpen or cs.seatbeltUnlatched or cs.parkingBrake or cs.accFaulted or cs.carNotReady or
                cs.steerFaultPermanent or cs.steerFaultTemporary or cs.espDisabled or cs.espActive or
                (CP.minEnableSpeed > cs.vEgo))
    brake = cs.brakePressed or cs.regenBraking
    # A fast stream can arrive one cycle before another. Do not infer active
    # control or a resume request from a contradictory combination.
    active_states = ('enabled', 'overriding', 'softDisabling')
    if (cc.enabled != ss.enabled or (not ss.enabled and cc.longActive) or
        ss.enabled != (ss.state in ('preEnabled', *active_states)) or ss.active != (ss.state in active_states)):
      return DrivingStatus('transition', '주행 상태 전환 중', '상태 확인 대기', **saved)
    if any(b.type == 'cancel' for b in cs.buttonEvents):
      return DrivingStatus('cancelling', '속도 보조 해제 중', '상태 확인 대기', **saved)
    if ss.enabled and blocking:
      return DrivingStatus('warning', '주행 경고 확인', '차량 상태와 경고 확인', **saved)
    if ss.enabled and ss.state == 'preEnabled' and not ss.active:
      detail = ('오토홀드 해제 상태 확인' if cs.brakeHoldActive else
                '브레이크 해제 후 활성화' if cs.brakePressed else
                '회생제동 해제 후 활성화' if cs.regenBraking else '활성화 조건 확인 중')
      return DrivingStatus('pre_enabled', '출발 대기', detail, **saved)
    if not ss.enabled:
      if blocking or brake or cs.brakeHoldActive or cs.gasPressed:
        detail = ('브레이크를 밟고 있어' if brake else '오토홀드 상태 확인' if cs.brakeHoldActive else
                  '가속페달을 밟고 있어' if cs.gasPressed else '경고와 차량 상태 확인')
        return DrivingStatus('blocked', '속도 보조 해제', detail, speed_label='이전 설정속도', **saved)
      if speed is None:
        return DrivingStatus('ready', '속도 보조 꺼짐', 'SET으로 속도 설정', action='set', **saved)
      return DrivingStatus('disabled', '속도 보조 해제', 'RES로 재개 요청', speed_label='이전 설정속도', action='resume', **saved)
    if not ss.active or ss.state not in ('enabled', 'overriding', 'softDisabling') or speed is None:
      return DrivingStatus('transition', '주행 상태 전환 중', '상태 확인 대기', **saved)
    if brake or cs.brakeHoldActive:
      return DrivingStatus('holding', '제동 상태 확인', '출발 조건 확인 중', **saved)
    if cs.gasPressed:
      if not cc.longActive:
        return DrivingStatus('override', '운전자 속도 조절 중', '페달 해제 후 보조 복귀', **saved)
      return DrivingStatus('transition', '주행 상태 전환 중', '페달 상태 확인 중', **saved)
    if not cc.longActive or cc.cruiseControl.override:
      return DrivingStatus('transition', '주행 상태 전환 중', '상태 확인 대기', **saved)
    if cs.standstill:
      return DrivingStatus('stopped', '속도 보조 정지 중', '주변 상황과 진행 조건 확인', **saved)
    return DrivingStatus('active', '속도 보조 중', **saved)
