"""Typed, audited phone settings. No arbitrary Params keys or vehicle commands.

The original three-setting API stays compatible. This separate catalog is read
on demand; it never turns a successful Params readback into runtime evidence.
"""
import copy
import json
import math
import os
from pathlib import Path

from openpilot.selfdrive.ui.sunnypilot.mici.korean.settings import SETTINGS, SettingsError

CATALOG = json.loads(Path(__file__).with_name('settings_catalog.json').read_text())
SPECS = {row['id']: row for row in CATALOG['rows']}
LABELS = {row['key']: row['title'] for row in CATALOG['rows']}


def valid_value(spec, value):
  if value is None:
    return spec.get('nullable', False)
  storage = spec['storage']
  if storage == 'bool' and type(value) is not bool:
    return False
  if storage == 'int' and type(value) is not int:
    return False
  if storage == 'float' and (type(value) not in (int, float) or type(value) is float and not math.isfinite(value)):
    return False
  if spec['type'] in ('enum', 'bool'):
    return any(type(value) is type(o['value']) and value == o['value'] or
               storage == 'float' and o['value'] is not None and value == o['value'] for o in spec['options'])
  if spec['type'] == 'number':
    if not spec['min'] <= value <= spec['max']:
      return False
    return math.isclose((value - spec['min']) / spec['step'], round((value - spec['min']) / spec['step']), abs_tol=1e-7)
  return False


class PhoneCatalog:
  def __init__(self, controller, *, quickboot_path=None):
    self.controller, self.store = controller, controller.store
    self.quickboot_path = Path(quickboot_path) if quickboot_path is not None else None

  def _read(self, key):
    try:
      return self.store.get(key)
    except Exception as exc:
      # A bad optional parameter must not take down the whole management page.
      raise SettingsError('저장값 읽기 실패', 'storage') from exc

  def _snapshot(self):
    values, errors = {}, set()
    for name, spec in SPECS.items():
      try:
        value = self._read(spec['key'])
        if value is not None and not valid_value(spec, value):
          raise SettingsError('저장값 형식 확인 필요', 'storage')
        values[name] = value
      except SettingsError:
        values[name] = None
        errors.add(name)
    return values, errors

  @staticmethod
  def _effective(values, key):
    spec = next(s for s in SPECS.values() if s['key'] == key)
    value = values.get(spec['id'])
    return value if value is not None else spec.get('default', False if spec['storage'] == 'bool' else None)

  def _capability(self, spec, state, values):
    cap, cp, sp = spec['capability'], state.get('cp') or {}, state.get('cp_sp') or {}
    has_long = cp.get('openpilotLongitudinalControl') is True
    has_icbm = sp.get('intelligentCruiseButtonManagementAvailable') is True and self._effective(values, 'IntelligentCruiseButtonManagement') is True
    if cap == 'tici_visual':
      return 'C4 화면 미지원'
    if cap == 'quickboot':
      if self.quickboot_path is None:
        return '기기 연결 필요'
      if state.get('release', True) or self._read('IsTestedBranch') is True or self._read('IsDevelopmentBranch') is True:
        return '개발판 전용'
      return ''
    if cap == 'later':
      return '후속 단계'
    if cap == 'test_mode':
      return '시험 도구 전용'
    if cap == 'development' and state.get('release', True):
      return '개발판 전용'
    if cap in ('device', 'development', 'sunnylink'):
      return ''
    if not cp:
      return '차량 확인 필요'
    # This product targets Hyundai. Do not approximate other brands' MADS and
    # safety-specific UI conditions from their name alone.
    if cp.get('brand') != 'hyundai':
      return '차량 미지원'
    if cap == 'owner' and cp.get('alphaLongitudinalAvailable') is not True:
      return '차량 미지원'
    if cap == 'long' and not has_long:
      return '콤마 크루즈 필요'
    if cap == 'hyundai_long' and (not has_long or cp.get('alphaLongitudinalAvailable') is not True):
      return '콤마 크루즈 필요'
    if cap == 'mads' and self._effective(values, 'Mads') is not True:
      return 'MADS 필요'
    if cap == 'torque' and cp.get('steerControlType') != 'torque':
      return '토크 조향 차량 필요'
    if cap == 'bsm' and cp.get('enableBsm') is not True:
      return '사각지대 감지 필요'
    if cap == 'icbm' and (has_long or sp.get('intelligentCruiseButtonManagementAvailable') is not True):
      return '순정 크루즈 지원 필요'
    if cap in ('cruise', 'increments') and not (has_long or has_icbm):
      return '크루즈 제어 필요'
    if cap == 'increments' and not ((has_long and cp.get('pcmCruise') is False) or has_icbm):
      return '설정속도 제어 미지원'
    return ''

  def _restriction(self, spec, state, values):
    if reason := self._capability(spec, state, values):
      return reason
    if reason := self.controller.write_guard():
      return reason
    if state.get('reason') or not state.get('parked'):
      return state.get('reason') or '주차 상태 확인 필요'
    if not self.controller.write_enabled:
      return 'C4 읽기 전용'
    if spec['id'] in SETTINGS:
      if reason := self.controller.block_reason(spec['id'], state):
        return reason
    key = spec['key']
    # Native locked toggles stay locked. Unknown keys are not read on stores
    # that cannot prove their presence; only upstream's actual lock key exists.
    if key == 'RecordFront' and self._read('RecordFrontLock') is True:
      return '기기 설정 잠김'
    for parent, allowed in spec.get('requires', {}).items():
      if self._effective(values, parent) not in allowed:
        return LABELS[parent] + ' 설정 필요'
    return ''

  def _choice_reason(self, spec, value, state, values):
    if spec['capability'] == 'sunnylink' and value is True and self._read('CompletedSunnylinkConsentVersion') != CATALOG['consent_version']:
      return 'C4에서 써니링크 동의 필요'
    if spec.get('excludes') and value is True and self._effective(values, spec['excludes']) is True:
      return LABELS[spec['excludes']] + ' 먼저 끄기'
    if spec['id'] == 'SpeedLimitMode' and value == 3:
      if reason := self._capability({**spec, 'capability': 'cruise'}, state, values):
        return reason
    return ''

  def view(self):
    with self.controller.lock:
      values, errors = self._snapshot()
      state = self.controller.inputs()
      rows = []
      # Three observed fields only; everything else is explicitly saved state.
      try:
        legacy = {row['id']: row for row in self.controller.view()['rows']}
      except SettingsError:
        legacy = {}
      for name, spec in SPECS.items():
        row = {k: copy.deepcopy(v) for k, v in spec.items() if k not in ('key', 'source', 'storage', 'requires', 'excludes', 'capability')}
        reason = '저장값 확인 필요' if errors else self._restriction(spec, state, values)
        capability = self._capability(spec, state, values)
        row.update(saved=values[name], current=None, status='저장값' if values[name] is not None else '미설정',
                   editable=not reason, blocked_reason=reason, supported=not capability,
                   support_reason=capability, read_error=name in errors)
        if name in legacy:
          row.update(current=legacy[name]['current'], status=legacy[name]['status'], notices=legacy[name]['notices'])
        for option in row.get('options', []):
          blocked = self._choice_reason(spec, option['value'], state, values)
          option.update(enabled=not blocked, reason=blocked)
        if row.get('unit') in ('speed', 'offset'):
          percent = row['unit'] == 'offset' and self._effective(values, 'SpeedLimitOffsetType') == 2
          row['unit'] = '%' if percent else 'km/h' if self._effective(values, 'IsMetric') is True else 'mph'
        rows.append(row)
      return {'schema': 1, 'groups': CATALOG['groups'], 'rows': rows, 'revision': self.controller.revision(values),
              'parked': bool(state.get('parked')), 'reason': self.controller.write_guard() or state.get('reason') or
              ('' if self.controller.write_enabled else 'C4 읽기 전용')}

  def save(self, name, value, revision, *, acknowledged=False):
    with self.controller.lock:
      if not isinstance(name, str) or name not in SPECS or not valid_value(SPECS[name], value):
        raise SettingsError('설정값 범위 확인', 'invalid')
      values, errors = self._snapshot()
      if errors:
        raise SettingsError('저장값 확인 필요', 'storage')
      if revision != self.controller.revision(values):
        raise SettingsError('설정이 바뀌었어. 새로고침 후 다시 선택해', 'conflict')
      spec, state = SPECS[name], self.controller.inputs()
      if reason := self._restriction(spec, state, values) or self._choice_reason(spec, value, state, values):
        raise SettingsError(reason)
      if not acknowledged:
        raise SettingsError('변경 내용 확인 필요', 'confirmation_required')
      key = spec['key']
      try:
        if key == 'QuickBootToggle':
          # Fixed device path supplied by the native owner, never by the phone.
          path = self.quickboot_path
          if path.is_symlink() or (path.exists() and not path.is_file()):
            raise OSError('unexpected prebuilt path')
          if value and not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            os.close(descriptor)
          elif not value:
            path.unlink(missing_ok=True)
        if value is None:
          self.store.remove(key)
        elif spec['storage'] == 'bool':
          self.store.put_bool(key, value, block=True)
        else:
          self.store.put(key, float(value) if spec['storage'] == 'float' else value, block=True)
        actual = self._read(key)
        if actual != value or (value is not None and not valid_value(spec, actual)):
          raise OSError('readback mismatch')
        if key == 'QuickBootToggle' and self.quickboot_path.is_file() != value:
          raise OSError('prebuilt readback mismatch')
      except Exception as exc:
        raise SettingsError('저장 결과 확인 필요', 'storage') from exc
      # No implicit restart, dependency writes, retries, or runtime acknowledgement.
