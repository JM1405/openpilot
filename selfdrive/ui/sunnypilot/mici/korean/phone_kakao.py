"""Paired Kakao observations and explicit readiness, never actuator commands.

This boundary deliberately does not write MapTargetVelocities or carControl.
An advisory code without a same-route distance/target must not become braking.
"""
import copy
import math
import secrets
import time

from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError

TTL = 3.0
MAX_EVENTS = 8
KINDS = {'camera', 'section', 'bump', 'sharp_turn', 'other'}


def number(value, low, high):
  return type(value) in (float, int) and math.isfinite(value) and low <= value <= high


class PhoneKakao:
  def __init__(self, service, *, clock=time.monotonic):
    self.service, self.clock = service, clock
    self.latest = None

  def challenge(self, token):
    with self.service.lock:
      session = self.service.session(token)
      # One outstanding request per paired session, with a C4-side deadline.
      session['kakao_challenge'] = (secrets.token_hex(16), self.clock())
      return {'challenge': session['kakao_challenge'][0], 'ttl_ms': int(TTL * 1000),
              'status': self.view(), 'control_enabled': False}

  def accept(self, token, csrf, data):
    with self.service.lock:
      session = self.service.authorize_write(token, csrf, observation=True)
      allowed = {'challenge', 'seq', 'mode', 'active', 'location_age_ms', 'gps_valid',
                 'speed_kph', 'route_matched', 'safety_age_ms', 'events'}
      if not isinstance(data, dict) or set(data) != allowed:
        raise PhoneError('카카오 자료 형식을 확인해')
      challenge, issued = session.get('kakao_challenge', ('', -math.inf))
      if not challenge or data['challenge'] != challenge or not 0 <= self.clock() - issued < TTL:
        raise PhoneError('카카오 수신 요청이 만료됐어', 'stale', 409)
      seq = data['seq']
      if type(seq) is not int or not 0 < seq < 2**53 or seq <= session.get('kakao_seq', 0):
        raise PhoneError('지난 카카오 자료야', 'sequence', 409)
      if data['mode'] not in ('free_drive', 'route'):
        raise PhoneError('카카오 안내 모드를 확인해')
      for key in ('active', 'gps_valid', 'route_matched'):
        if type(data[key]) is not bool:
          raise PhoneError('카카오 상태를 확인해')
      for key in ('location_age_ms', 'safety_age_ms'):
        if data[key] is not None and not number(data[key], 0, 2**53 - 1):
          raise PhoneError('카카오 자료 시각을 확인해')
      if data['speed_kph'] is not None and not number(data['speed_kph'], 0, 250):
        raise PhoneError('카카오 속도 범위를 확인해')
      if data['mode'] == 'free_drive' and data['route_matched']:
        raise PhoneError('무목적지 GPS를 경로 매칭으로 처리할 수 없어')
      events = data['events']
      if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise PhoneError('안전 안내 개수를 확인해')
      clean = []
      ids = set()
      for event in events:
        fields = {'id', 'code', 'kind', 'distance_m', 'distance_basis', 'limit_kph', 'passed', 'variable'}
        if not isinstance(event, dict) or set(event) != fields:
          raise PhoneError('안전 안내 항목을 확인해')
        if (not isinstance(event['id'], str) or not 1 <= len(event['id']) <= 80 or event['id'] in ids or
            not isinstance(event['code'], str) or not 1 <= len(event['code']) <= 100 or
            not isinstance(event['kind'], str) or event['kind'] not in KINDS or
            type(event['passed']) is not bool or type(event['variable']) is not bool):
          raise PhoneError('안전 안내 식별자를 확인해')
        ids.add(event['id'])
        if event['distance_basis'] not in ('same_route', 'unknown'):
          raise PhoneError('안내 거리의 근거를 확인해')
        if event['distance_basis'] == 'same_route':
          if not data['route_matched'] or not number(event['distance_m'], 0, 100000):
            raise PhoneError('같은 경로의 거리가 아니야')
        elif event['distance_m'] is not None:
          raise PhoneError('확인되지 않은 거리를 사용할 수 없어')
        if event['limit_kph'] is not None:
          if event['kind'] not in ('camera', 'section') or not number(event['limit_kph'], 1, 160):
            raise PhoneError('급커브/방지턱에 임의 속도를 넣을 수 없어')
        clean.append(copy.deepcopy(event))
      now = self.clock()
      session['kakao_seq'] = seq
      session.pop('kakao_challenge', None)  # A request cannot be replayed.
      self.latest = {**copy.deepcopy(data), 'events': clean, 'session_id': session['id'],
                     'received': now, 'transit_bound_ms': (now - issued) * 1000,
                     'expires': issued + TTL}
      return self.view()

  def view(self):
    with self.service.lock:
      self.service._expire()
      item, now = self.latest, self.clock()
      baseline = {'received': False, 'location_fresh': False, 'events': [], 'control_enabled': False,
                  'scope': 'sdk_observation', 'connection_mode': self.service.mode, 'reason': '카카오 수신 전 또는 만료'}
      ids = {s['id'] for s in self.service.sessions.values()}
      if not item or item['session_id'] not in ids or not item['received'] <= now < item['expires']:
        return baseline
      elapsed_ms = (now - item['received']) * 1000 + item['transit_bound_ms']
      def fresh(key):
        return item[key] is not None and item[key] + elapsed_ms < TTL * 1000
      valid = item['active'] and item['gps_valid'] and fresh('location_age_ms')
      rows = []
      for raw in item['events'] if item['active'] and fresh('safety_age_ms') else []:
        event = copy.deepcopy(raw)
        if event['passed']:
          reason = '이미 통과'
        elif not valid:
          reason = '위치 입력 대기/만료'
        elif event['distance_basis'] != 'same_route':
          reason = '진행 도로와 남은 거리 미확인'
        elif event['kind'] == 'sharp_turn':
          reason = '급커브 알림 수신 · 곡률/통과속도 자료 없음'
        elif event['kind'] == 'bump':
          reason = '방지턱 알림 수신 · 목표속도 규격 미확인'
        elif event['variable']:
          reason = '가변 제한속도 현재 효력 미확인'
        elif event['limit_kph'] is None:
          reason = '유효한 제한속도 없음'
        else:
          reason = '거리/단속속도 수신 · 제어 연결 전'
        event['reason'] = reason
        event['control_eligible'] = False
        rows.append(event)
      return {**baseline, 'received': True, 'seq': item['seq'], 'mode': item['mode'],
              'location_fresh': bool(valid), 'route_matched': bool(valid and item['route_matched']),
              'speed_kph': item['speed_kph'] if valid else None, 'events': rows,
              'reason': ('카카오 수신 중지' if not item['active'] else
                         '카카오 자료 수신 · 제어 연결 전' if valid else 'SDK 연결됨 · 새 위치 대기')}
