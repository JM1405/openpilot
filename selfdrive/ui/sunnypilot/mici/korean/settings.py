"""Korean driving settings: saved Params and observed runtime are independent.

No process restart or vehicle command. Only three existing boolean Params can
be written, after a fresh parked/disengaged check and optimistic revision check.
"""
import hashlib
import json
import math
import threading

from openpilot.selfdrive.ui.sunnypilot.mici.korean.state import fresh

SETTINGS = {
  'owner': {'key': 'AlphaLongitudinalEnabled', 'title': '크루즈 담당', 'options': ['순정 SCC', '콤마'],
            'description': '가속과 제동을 맡을 시스템을 선택해. 변경 후 재시작이 필요해.', 'restart': True},
  'mode': {'key': 'ExperimentalMode', 'title': '기본 ACC · E2E', 'options': ['ACC', 'E2E'],
           'description': '콤마가 속도를 제어할 때 사용할 기본 방식이야. 자동 전환 설정은 유지해.', 'restart': False},
  'mads': {'key': 'Mads', 'title': '조향·속도 분리', 'options': ['끄기', 'MADS 켜기'],
           'description': '조향과 속도 보조를 분리해 사용해. 변경 후 재시작이 필요해.', 'restart': True},
}
NOTICES = {
  'owner': ['콤마 속도 제어는 시험 단계 기능이야.', '차량에 따라 자동 긴급 제동(AEB)이 꺼질 수 있어.',
            '저장 후 재시작하고 현재 크루즈 담당을 확인해.'],
  'mode': ['E2E는 주행 모델이 가속과 제동을 판단하는 시험 기능이야.', '설정속도는 상한이며 잘못 판단할 수 있어.',
           '항상 도로를 주시하고 직접 조작할 준비가 필요해.'],
  'mads': ['MADS 변경은 재시작 후 반영돼.', '브레이크·버튼의 세부 동작 설정은 그대로 유지해.',
           '다시 시작한 뒤 현재 설정과 조향 상태를 확인해.'],
}


def notices(name):
  off = {'owner': ['순정 SCC 선택을 저장해.', '재시작한 뒤 현재 크루즈 담당이 순정인지 확인해.'],
         'mode': ['기본 방식을 ACC로 저장해.', '자동 전환 기능이 켜져 있으면 현재 방식은 달라질 수 있어.'],
         'mads': NOTICES['mads']}
  return [off[name], NOTICES[name]]


def sample(sm, name, now, started_frame, *, static=False):
  if name not in sm.services or not sm.seen[name] or not sm.valid[name] or sm.recv_frame[name] < started_frame:
    return None
  timestamp = sm.recv_time[name]
  if timestamp > now or (not static and not fresh(timestamp, now, .5)):
    return None
  return sm[name].to_dict()


def observed(sm, now, started_frame=0, *, release=False):
  def get(name):
    return sample(sm, name, now, started_frame)
  cs, cc, ss, sp = (get(n) for n in ('carState', 'carControl', 'selfdriveState', 'selfdriveStateSP'))
  cp = sample(sm, 'carParams', now, started_frame, static=True)
  speed = cs.get('vEgo') if cs else None
  vehicle_valid = bool(cs and cs.get('canValid') and isinstance(speed, (int, float)) and math.isfinite(speed) and speed >= 0)
  reason = ''
  if not vehicle_valid or not all((cc, ss, sp)):
    reason = '차량·보조 상태를 확인할 수 없어'
  elif cs.get('gearShifter') != 'park' or speed >= .1 or not cs.get('standstill'):
    reason = 'P단에 주차한 뒤 변경할 수 있어'
  elif (cc.get('enabled') or cc.get('latActive') or cc.get('longActive') or ss.get('enabled') or
        sp.get('mads', {}).get('enabled') or sp.get('mads', {}).get('active')):
    reason = '조향·속도 보조를 해제한 뒤 변경해'
  owner = cp.get('openpilotLongitudinalControl') if cp and vehicle_valid else None
  mode, dynamic = None, get('longitudinalPlanSP')
  if owner and ss:
    mode = ss.get('experimentalMode')
    if dynamic and dynamic.get('dec', {}).get('active'):
      mode = dynamic['dec'].get('state') == 'blended'
  return {'parked': not reason, 'reason': reason, 'cp': cp, 'release': release,
          'values': {'owner': owner, 'mode': mode, 'mads': sp.get('mads', {}).get('available') if sp else None},
          'dynamic': dynamic.get('dec', {}).get('active') if dynamic else None,
          'lateral_active': cc.get('latActive') if cc and vehicle_valid else None}


class SettingsError(ValueError):
  def __init__(self, message, code='blocked'):
    super().__init__(message)
    self.code = code


class SettingsController:
  def __init__(self, store, inputs, *, write_enabled=True):
    self.store = store  # Params-compatible get/put_bool; PC uses an isolated JSON store
    self.inputs = inputs  # reevaluated on every read and save
    self.write_enabled = bool(write_enabled)
    self.write_guard = lambda: ''
    self.lock = threading.RLock()

  def saved(self):
    return {name: self.read(spec['key']) for name, spec in SETTINGS.items()}

  def read(self, key):
    try:
      value = self.store.get(key)
      if value is not None and type(value) is not bool:
        raise ValueError('Invalid stored type')
      return value
    except (OSError, RuntimeError, ValueError) as exc:
      raise SettingsError('저장된 설정을 읽지 못했어. 다시 확인해', 'storage') from exc

  @staticmethod
  def revision(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:24]

  def block_reason(self, name, state):
    if reason := self.write_guard():
      return reason
    if state['reason']:
      return state['reason']
    if not self.write_enabled:
      return '초기 주차 확인은 읽기 전용이야'
    cp = state['cp']
    if not cp:
      return '현재 차량 구성을 확인할 수 없어'
    if name == 'owner':
      if state['release']:
        return '이 배포판에서는 크루즈 담당을 바꿀 수 없어'
      if cp.get('brand') != 'hyundai' or not cp.get('alphaLongitudinalAvailable'):
        return '현재 차량 구성은 담당 전환을 지원하지 않아'
    if name == 'mode' and state['values']['owner'] is not True:
      return '콤마 크루즈 적용을 확인한 뒤 선택할 수 있어'
    return ''

  @staticmethod
  def supported(name, state):
    """Return only capabilities confirmed by the current vehicle snapshot.

    A missing/stale CarParams snapshot is unknown, not an invitation to expose
    a setting. The phone UI uses this field to hide unsupported rows while the
    device API still returns the row for diagnostics.
    """
    cp = state['cp']
    if not cp:
      return False
    if name == 'owner':
      return cp.get('brand') == 'hyundai' and cp.get('alphaLongitudinalAvailable') is True
    if name == 'mode':
      return cp.get('openpilotLongitudinalControl') is True or cp.get('alphaLongitudinalAvailable') is True
    return name == 'mads'

  def view(self):
    with self.lock:
      values, state = self.saved(), self.inputs()
      rows = []
      for name, spec in SETTINGS.items():
        actual, saved = state['values'][name], values[name]
        if name == 'mode' and self.read('DynamicExperimentalControl') is True and state['dynamic'] is None:
          actual = None  # dynamic planner has not confirmed its current choice
        if actual is None:
          status = '현재 상태 확인 불가' if name != 'mode' or state['values']['owner'] is not False else '순정 크루즈 사용 중'
        elif saved is None:
          status = '저장된 선택 없음'
        elif name == 'mode' and state['dynamic']:
          status = '자동 전환 중 · 현재 방식 표시'
        elif saved == actual:
          status = '현재 반영 확인'
        else:
          status = '재시작 필요' if spec['restart'] else '반영 대기'
        supported = self.supported(name, state)
        blocked = self.block_reason(name, state) if supported else '현재 차량에서 지원 여부를 확인할 수 없어'
        rows.append({'id': name, **{k: v for k, v in spec.items() if k != 'key'}, 'saved': saved,
                     'current': actual, 'status': status, 'supported': supported,
                     'editable': supported and not blocked, 'blocked_reason': blocked,
                     'notices': notices(name)})
      return {'revision': self.revision(values), 'parked': state['parked'], 'reason': state['reason'],
              'lateral_active': state['lateral_active'], 'rows': rows}

  def save(self, name, value, revision, *, acknowledged=False):
    with self.lock:
      if not isinstance(name, str) or name not in SETTINGS or type(value) is not bool:
        raise SettingsError('올바른 설정값이 아니야', 'invalid')
      if revision != self.revision(self.saved()):
        raise SettingsError('다른 곳에서 설정이 바뀌었어. 새 값을 확인하고 다시 선택해', 'conflict')
      if reason := self.block_reason(name, self.inputs()):
        raise SettingsError(reason)
      if not acknowledged:
        raise SettingsError('변경 내용을 먼저 확인해', 'confirmation_required')
      key = SETTINGS[name]['key']
      try:
        self.store.put_bool(key, value, block=True)
        if self.store.get(key) is not value:
          raise OSError('readback mismatch')
      except (OSError, RuntimeError) as exc:
        raise SettingsError('저장을 확인하지 못했어. 현재 값을 다시 확인해', 'storage') from exc
      # Never fabricate runtime acknowledgement or restart the device here.
      return self.view()
