"""Local phone management views for device, version and model state.

The controller deliberately keeps model selection disabled by default.  The
first C4 A/B candidate must stay on CD210; a later, explicitly configured
candidate can enable the already-tested request path without changing the API.
"""
import hashlib
import json
import math

from openpilot.selfdrive.ui.sunnypilot.mici.korean.settings import SettingsError
from openpilot.sunnypilot.models.default_model import DEFAULT_MODEL


def _safe(store, key, default=None):
  try:
    value = store.get(key)
    return default if value is None else value
  except (OSError, RuntimeError, ValueError, TypeError):
    return default


def _masked(value):
  value = str(value or '')
  return ('••••' + value[-6:]) if value else '확인 불가'


class PhoneManagement:
  def __init__(self, store, settings, model_input, *, allow_model_change=False, write_guard=lambda: ''):
    self.store = store
    self.settings = settings
    self.model_input = model_input
    self.allow_model_change = bool(allow_model_change)
    self.write_guard = write_guard

  def device(self):
    runtime = self.model_input()
    device_state = runtime.get('deviceState') or {}
    hardware = device_state.get('deviceType') or _safe(self.store, 'DeviceType', '')
    label = {'mici': 'comma four (MICI)', 'tici': 'comma three'}.get(str(hardware), str(hardware) or '장치 확인 필요')
    commit = str(_safe(self.store, 'GitCommit', '') or '')
    cp = runtime.get('carParams') or {}
    return {
      'product': 'Koranipilot',
      'hardware': label,
      'identifier': _masked(_safe(self.store, 'HardwareSerial', '') or _safe(self.store, 'DongleId', '')),
      'version': str(_safe(self.store, 'Version', '확인 불가')),
      'branch': str(_safe(self.store, 'GitBranch', '확인 불가')),
      'commit': commit[:10] if commit else '확인 불가',
      'vehicle': str(cp.get('brand') or '확인 불가'),
      'runtime_fresh': bool(runtime.get('fresh')),
      'scope': 'same_network_local_management',
    }

  @staticmethod
  def _bundle(raw):
    if not isinstance(raw, dict):
      return None
    ref = raw.get('ref')
    if not isinstance(ref, str) or not ref:
      return None
    index = raw.get('index')
    if type(index) is not int or index < 0:
      return None
    return {
      'ref': ref,
      'index': index,
      'name': str(raw.get('displayName') or raw.get('internalName') or ref)[:80],
      'generation': raw.get('generation') if type(raw.get('generation')) is int else None,
      'status': str(raw.get('status') or 'notDownloading'),
    }

  @staticmethod
  def _progress(raw):
    values = []
    for model in raw.get('models', []) if isinstance(raw, dict) else []:
      if not isinstance(model, dict):
        continue
      for key in ('artifact', 'metadata'):
        progress = model.get(key, {}).get('downloadProgress', {}).get('progress')
        if isinstance(progress, (int, float)) and math.isfinite(progress):
          values.append(max(0., min(100., float(progress))))
    return round(sum(values) / len(values), 1) if values else None

  def models(self):
    runtime = self.model_input()
    manager = runtime.get('modelManagerSP') if runtime.get('fresh') else None
    manager = manager if isinstance(manager, dict) else {}
    active_raw = manager.get('activeBundle') if isinstance(manager.get('activeBundle'), dict) else {}
    selected_raw = manager.get('selectedBundle') if isinstance(manager.get('selectedBundle'), dict) else {}
    active = self._bundle(active_raw)
    selected = self._bundle(selected_raw)
    available = [{'ref': '', 'index': None, 'name': f'{DEFAULT_MODEL} (기본)', 'generation': None,
                  'status': 'active' if active is None else 'available'}]
    seen = set()
    for raw in manager.get('availableBundles', []) if isinstance(manager.get('availableBundles'), list) else []:
      bundle = self._bundle(raw)
      if bundle and bundle['ref'] not in seen:
        seen.add(bundle['ref'])
        available.append(bundle)
    pending_index = _safe(self.store, 'ModelManager_DownloadIndex')
    current = (active or available[0]) if runtime.get('fresh') else {
      'ref': None, 'index': None, 'name': '현재 모델 확인 불가', 'generation': None, 'status': 'unknown'}
    parked = self.settings.view()['parked']
    reason = ''
    if self.write_guard():
      reason = self.write_guard()
    elif not runtime.get('fresh'):
      reason = '모델 관리 상태를 확인할 수 없어'
    elif not self.allow_model_change:
      reason = '초기 C4 A/B 검증에서는 CD210을 고정해'
    elif not parked:
      reason = self.settings.view()['reason']
    result = {
      'default_model': DEFAULT_MODEL,
      'current': current,
      'requested': selected,
      'pending_index': pending_index if type(pending_index) is int else None,
      'progress': self._progress(selected_raw),
      'available': available,
      'editable': not reason,
      'blocked_reason': reason,
      'baseline_fixed': not self.allow_model_change,
      'runtime_fresh': bool(runtime.get('fresh')),
    }
    result['revision'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]
    return result

  def request_model(self, ref, revision, *, acknowledged=False):
    view = self.models()
    if revision != view['revision']:
      raise SettingsError('모델 상태가 바뀌었어. 목록을 다시 확인해', 'conflict')
    if not acknowledged:
      raise SettingsError('모델 변경 내용을 먼저 확인해', 'confirmation_required')
    if view['blocked_reason']:
      raise SettingsError(view['blocked_reason'], 'baseline_fixed' if view['baseline_fixed'] else 'blocked')
    if not isinstance(ref, str) or len(ref) > 160:
      raise SettingsError('올바른 모델이 아니야', 'invalid')
    candidate = next((item for item in view['available'] if item['ref'] == ref), None)
    if candidate is None:
      raise SettingsError('현재 장치의 모델 목록에 없어', 'invalid')
    try:
      if ref == '':
        self.store.remove('ModelManager_DownloadIndex')
        self.store.remove('ModelManager_ActiveBundle')
        if self.store.get('ModelManager_DownloadIndex') is not None or self.store.get('ModelManager_ActiveBundle') is not None:
          raise OSError('readback mismatch')
      else:
        self.store.put('ModelManager_DownloadIndex', candidate['index'], block=True)
        if self.store.get('ModelManager_DownloadIndex') != candidate['index']:
          raise OSError('readback mismatch')
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
      raise SettingsError('모델 변경 요청 저장을 확인하지 못했어', 'storage') from exc
    return {'ref': ref, 'name': candidate['name'], 'outcome': 'requested',
            'message': '모델 변경을 요청했어. 다운로드·실제 적용 상태를 따로 확인해.'}

  def overview(self):
    return {'device': self.device(), 'settings': self.settings.view(), 'models': self.models()}
