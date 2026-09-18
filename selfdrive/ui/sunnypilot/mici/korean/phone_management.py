"""Guarded phone model selection, queued downloads and independently observed inference."""
import hashlib
import json
import math
import uuid

from openpilot.sunnypilot.models.selection import REQUEST, RESULT, bundle_signature, selection_lock

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
    active_raw = manager.get('activeBundle') or {}
    selected_raw = manager.get('selectedBundle') or {}
    configured = self._bundle(active_raw)
    selected = self._bundle(selected_raw)
    default = {'ref': '', 'index': None, 'name': f'{DEFAULT_MODEL} (기본)', 'generation': None, 'status': 'available'}
    available = [default]
    seen = set()
    for raw in manager.get('availableBundles', []):
      bundle = self._bundle(raw)
      if bundle and bundle['ref'] not in seen:
        seen.add(bundle['ref'])
        available.append(bundle)
    configured = (configured or dict(default)) if runtime.get('fresh') else None
    if configured is not None:
      configured['signature'] = bundle_signature(active_raw) if active_raw.get('ref') else 'default'
    observed = runtime.get('modelDataV2SP') or {}
    running = bool(observed.get('modelIdentityKnown'))
    current = {'ref': observed.get('modelRef'), 'signature': observed.get('modelSignature'), 'name': observed.get('modelName'), 'status': 'running'} if running else {
      'ref': None, 'name': '실행 모델 확인 대기', 'status': 'unknown'}
    pending_index = _safe(self.store, 'ModelManager_DownloadIndex')
    pending_index = pending_index if type(pending_index) is int else None
    request = _safe(self.store, REQUEST, {})
    request = request if isinstance(request, dict) else {}
    last = _safe(self.store, RESULT, {})
    last = last if isinstance(last, dict) else {}
    queued = next((x for x in available if x['index'] == pending_index), None) if pending_index is not None else None
    busy = pending_index is not None or (selected is not None and selected['status'] == 'downloading')
    parked = self.settings.view()['parked']
    reason = self.write_guard()
    if not reason and not runtime.get('fresh'):
      reason = '모델 관리 상태를 확인할 수 없어'
    elif not reason and not self.allow_model_change:
      reason = '이 설치본에서는 모델 변경이 잠겨 있어'
    elif not reason and not parked:
      reason = self.settings.view()['reason']
    state = 'unknown'
    message = '모델 관리 상태를 확인할 수 없어'
    if runtime.get('fresh'):
      if busy:
        state = 'downloading' if selected and selected['status'] == 'downloading' else 'queued'
        message = '모델 다운로드 중' if state == 'downloading' else '변경 요청됨 · P단·정차·보조 해제 상태에서 다운로드'
      elif last.get('state') == 'failed':
        state, message = 'failed', '다운로드 실패 · 기존 모델 유지. 다시 선택해 재시도할 수 있어'
      elif running and configured and current['ref'] == configured['ref'] and current['signature'] == configured['signature']:
        state, message = 'running', '실제 모델 실행 확인'
      else:
        state, message = 'ready', '다음 기동 모델 준비됨 · 실행 확인 대기'
    result = {
      'schema': 2, 'default_model': DEFAULT_MODEL, 'current': current, 'configured': configured,
      'requested': selected or queued, 'pending_index': pending_index,
      'progress': self._progress(selected_raw), 'available': available,
      'editable': not reason and not busy, 'can_restore_default': not reason,
      'blocked_reason': reason or ('진행 중인 요청이 있어. 기본 모델로 복귀하면 취소돼' if busy else ''),
      'baseline_fixed': not self.allow_model_change, 'runtime_fresh': bool(runtime.get('fresh')),
      'running_confirmed': running, 'configured_running': bool(running and configured and current['ref'] == configured['ref'] and current['signature'] == configured['signature']), 'state': state, 'message': message, 'last_result': last,
    }
    # UI progress and inference frames must not invalidate an unchanged selection.
    revision = {'available': manager.get('availableBundles', []), 'configured': configured,
                'pending': pending_index, 'request': request, 'reason': reason, 'busy': busy}
    revision['available'] = [bundle_signature(x) for x in manager.get('availableBundles', [])]
    result['revision'] = hashlib.sha256(json.dumps(revision, sort_keys=True).encode()).hexdigest()[:24]
    return result

  def request_model(self, ref, revision, *, acknowledged=False):
    with selection_lock(self.store):
      view = self.models()
      if revision != view['revision']:
        raise SettingsError('모델 상태가 바뀌었어. 목록을 다시 확인해', 'conflict')
      if not acknowledged:
        raise SettingsError('모델 변경 내용을 먼저 확인해', 'confirmation_required')
      if not (view['can_restore_default'] if ref == '' else view['editable']):
        raise SettingsError(view['blocked_reason'], 'baseline_fixed' if view['baseline_fixed'] else 'blocked')
      if not isinstance(ref, str) or len(ref) > 160:
        raise SettingsError('올바른 모델이 아니야', 'invalid')
      candidate = next((item for item in view['available'] if item['ref'] == ref), None)
      if candidate is None:
        raise SettingsError('현재 장치의 모델 목록에 없어', 'invalid')
      try:
        if ref == '':
          self.store.remove('ModelManager_DownloadIndex')
          self.store.remove(REQUEST)
          self.store.remove('ModelManager_ActiveBundle')
          self.store.put(RESULT, {'state': 'ready', 'ref': ''}, block=True)
          if any(self.store.get(k) is not None for k in ('ModelManager_DownloadIndex', REQUEST, 'ModelManager_ActiveBundle')):
            raise OSError('readback mismatch')
        else:
          raw = next((x for x in self.model_input().get('modelManagerSP', {}).get('availableBundles', []) if x.get('ref') == ref), None)
          if raw is None or self.models()['revision'] != revision:
            raise SettingsError('모델 목록이 바뀌었어. 다시 확인해', 'conflict')
          request = {'id': uuid.uuid4().hex, 'ref': ref, 'index': candidate['index'], 'signature': bundle_signature(raw)}
          self.store.put(REQUEST, request, block=True)
          self.store.put('ModelManager_DownloadIndex', candidate['index'], block=True)
          self.store.put(RESULT, {'state': 'queued', 'ref': ref, 'id': request['id']}, block=True)
          if self.store.get('ModelManager_DownloadIndex') != candidate['index'] or self.store.get(REQUEST) != request:
            raise OSError('readback mismatch')
      except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise SettingsError('모델 변경 요청 저장을 확인하지 못했어', 'storage') from exc
      return {'ref': ref, 'name': candidate['name'], 'outcome': 'requested',
              'message': '기본 모델 복귀를 요청했어. 다음 기동 후 실행 상태를 확인해.' if ref == '' else
                         '모델 변경을 요청했어. 주차 상태에서 다운로드하며 다음 기동 때 실행을 확인해.'}

  def overview(self):
    return {'device': self.device(), 'settings': self.settings.view(), 'models': self.models()}
