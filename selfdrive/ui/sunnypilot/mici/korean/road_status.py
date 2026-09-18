"""Read-only road status. Only the UI thread polls IPC; HTTP reads immutable copies."""
import copy
import threading
import time
from datetime import date

LEASE_SECONDS = .15


def describe(state, gps_valid):
  dataset = state.get('dataset', {})
  estimated = bool(state['fresh'] and state['input_available'] and state.get('motion_estimated', False))
  usable = gps_valid or estimated
  lines = ['GPS: 위치 수신 중' if gps_valid else '위치: 차량 이동으로 추정 중' if estimated else 'GPS: 새 위치 대기']
  if not state['fresh']:
    return lines + ['도로 자료: 상태 확인 대기', '도로 정보: 연결 확인 필요', '새 상태를 받으면 다시 표시해']
  kind = dataset.get('state')
  lines.append({'ready': '도로 자료: 읽기 확인', 'loading': '도로 자료: 새 자료 확인 중',
                'missing': '도로 자료: 준비 필요', 'invalid': '도로 자료: 파일 확인 필요'}.get(kind, '도로 자료: 상태 확인 필요'))
  status = state['input_status']
  if state['input_available'] and usable:
    reason = '도로 정보: 현재 도로만 확인' if status in ('currentRoadOnly','currentRoadKakaoCamera') else '도로 정보: 확인됨'
  elif status in ('lowSpeedHold', 'lowSpeedHoldExpired', 'headingUnavailableAtLowSpeed'):
    reason = '도로 정보: 저속으로 사용 보류'
  elif status in ('ambiguousRoad', 'ambiguousRoadGeometry', 'lowSpeedRoadAmbiguous'):
    reason = '도로 정보: 현재 도로 구분 대기'
  elif status in ('junctionUncertain', 'roadBoundaryUncertain'):
    reason = '도로 정보: 교차로·경계 확인 대기'
  elif status.startswith('route'):
    reason = '도로 정보: 경로·위치 재확인 중'
  elif status == 'unusableOrOldRoad':
    reason = '도로 정보: 이용 조건·기준일 확인'
  elif status in ('warmingUp', 'transitionConfirming', 'waitingForFreshFix'):
    reason = '도로 정보: 새 위치로 재확인 중'
  elif status in ('datasetChanged', 'datasetLoading'):
    reason = '도로 정보: 자료 교체로 사용 보류'
  elif status in ('datasetUnavailable', 'datasetModifiedInPlace', 'providerError'):
    reason = '도로 정보: 자료 확인 후 다시 사용'
  elif status in ('noRoadMatch', 'positionJump', 'implausibleProgress', 'implausibleTransition', 'disconnectedTransition',
                  'backwardsProgress', 'transitionGeometryGap', 'lowSpeedPositionUncertain'):
    reason = '도로 정보: 위치·진행 방향 재확인'
  else:
    reason = '도로 정보: 새 입력 대기'
  lines.append(reason)
  if kind == 'ready':
    try:
      updated = date.fromisoformat(dataset.get('latest_road_date', '')).isoformat()
    except (ValueError, TypeError):
      updated = '확인 필요'
    lines.append('최근 도로 기준일: ' + updated)
    if status in ('derivedWithKakaoCamera','currentRoadKakaoCamera') and state['input_available'] and usable:
      lines.append('카카오 단속: 도로·방향 확인')
    else:
      lines.append('카메라·방지턱: 검증 자료 없음' if dataset.get('verified_events') == 0 else '카메라·방지턱: 도로·시점 재확인')
  else:
    lines.append('위치와 자료가 확인될 때까지 기다려 줘')
  return lines


class RoadStatusMonitor:
  def __init__(self, *, clock=time.monotonic):
    self.clock, self.reader = clock, None
    self.lock = threading.Lock()
    self.state = {'fresh': False, 'input_status': 'awaitingRoadService', 'input_available': False, 'dataset': {}}
    self.stamp = 0.
    self.input_deadline = 0.

  def attach(self, reader):
    if self.reader is not None:
      raise RuntimeError('road status already attached')
    self.reader = reader

  def update(self):
    if self.reader is None:
      return
    now = self.clock()
    road = self.reader(now)
    from dataclasses import asdict
    with self.lock:
      self.stamp = self.reader.guard.stamp / 1e9
      self.input_deadline = self.reader.deadline / 1e9
      self.state = {'fresh': self.reader.status != 'invalidRoadIpc', 'input_status': self.reader.status,
                    'input_available': road is not None, 'motion_estimated': bool(road is not None and road.context.motion_estimated),
                    'dataset': asdict(self.reader.dataset)}

  def view(self):
    with self.lock:
      state = copy.deepcopy(self.state)
      # Reading over HTTPS or redrawing a stopped UI cannot renew the status.
      state['fresh'] = state['fresh'] and self.stamp > 0 and -.01 <= self.clock() - self.stamp <= LEASE_SECONDS
      if not state['fresh']:
        state.update(input_available=False, motion_estimated=False, input_status='awaitingRoadService', dataset={})
      elif state['input_available'] and self.clock() >= self.input_deadline:
        state.update(input_available=False, motion_estimated=False, input_status='inputExpired')
      return state

  def close(self):
    if self.reader is not None:
      self.reader.close()
      self.reader = None
    with self.lock:
      self.stamp = 0.
      self.state.update(fresh=False, input_available=False, motion_estimated=False, dataset={})
