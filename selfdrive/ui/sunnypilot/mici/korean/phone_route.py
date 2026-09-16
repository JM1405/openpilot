"""Ephemeral paired route display and bounded observation hints; no actuation."""
import copy
import hashlib
import struct
import math
import secrets
import time

from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_kakao import number
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError

TTL = 3.0
MAX_POINTS = 2048  # v1 compatibility
MAX_ROUTE_POINTS = 65536
CHUNK_POINTS = 2048
STATES = {'idle', 'planning', 'active', 'rerouting', 'ended', 'error'}
LABELS = {'idle': '목적지 대기', 'planning': '경로 탐색 중', 'active': '안내 중',
          'rerouting': '재탐색 중', 'ended': '안내 종료', 'error': '경로 확인 필요'}


def short_text(value, limit):
  return isinstance(value, str) and len(value) <= limit and all(ord(c) >= 32 for c in value)


class PhoneRoute:
  def __init__(self, service, *, clock=time.monotonic):
    self.service, self.clock, self.latest = service, clock, None

  def challenge(self, token):
    with self.service.lock:
      session = self.service.session(token)
      session['route_challenge'] = (secrets.token_hex(16), self.clock())
      return {'challenge': session['route_challenge'][0], 'ttl_ms': 3000, 'status': self.view(), 'upload': self.upload_view(session)}

  def accept(self, token, csrf, data):
    with self.service.lock:
      session = self.service.authorize_write(token, csrf, observation=True)
      v2 = data.get('protocol') == 2 if isinstance(data, dict) else False
      fields = {'challenge', 'seq', 'revision', 'state', 'destination', 'geometry', 'geometry_status',
                'total_m', 'total_s', 'remaining_m', 'remaining_s', 'location_age_ms', 'matched'}
      if v2:
        fields = fields - {'geometry'} | {'protocol', 'shape_id', 'point_count'}
        if 'turn' in data:
          fields.add('turn')
      if not isinstance(data, dict) or set(data) != fields:
        raise PhoneError('경로 자료 형식을 확인해')
      nonce, issued = session.get('route_challenge', ('', -math.inf))
      if not nonce or nonce != data['challenge'] or not 0 <= self.clock() - issued < TTL:
        raise PhoneError('경로 수신 요청이 만료됐어', 'stale', 409)
      seq, rev = data['seq'], data['revision']
      if type(seq) is not int or not 0 < seq < 2**53 or seq <= session.get('route_seq', 0):
        raise PhoneError('지난 경로 자료야', 'sequence', 409)
      if type(rev) is not int or not 0 <= rev < 2**53 or rev < session.get('route_revision', -1):
        raise PhoneError('지난 경로 버전이야', 'revision', 409)
      if not isinstance(data['state'], str) or data['state'] not in STATES or not short_text(data['destination'], 120):
        raise PhoneError('경로 상태를 확인해')
      if type(data['matched']) is not bool or not isinstance(data['geometry_status'], str) or data['geometry_status'] not in ('full', 'unavailable', 'too_large'):
        raise PhoneError('경로 위치·형상을 확인해')
      for key, high in [('total_m', 3000000), ('remaining_m', 3000000), ('total_s', 604800), ('remaining_s', 604800), ('location_age_ms', 2**53-1)]:
        if data[key] is not None and not number(data[key], 0, high):
          raise PhoneError('경로 거리·시각을 확인해')
      points = data.get('geometry', [])
      if v2:
        if type(data['protocol']) is not int or type(data['point_count']) is not int or not 0 <= data['point_count'] <= MAX_ROUTE_POINTS:
          raise PhoneError('경로 좌표 개수를 확인해')
        if data['geometry_status'] == 'full':
          if not 2 <= data['point_count'] <= MAX_ROUTE_POINTS or not isinstance(data['shape_id'], str) or len(data['shape_id']) != 64 or any(c not in '0123456789abcdef' for c in data['shape_id']):
            raise PhoneError('경로 식별자를 확인해')
        elif data['shape_id'] != '' or data['point_count'] != 0:
          raise PhoneError('없는 경로 형상을 보낼 수 없어')
      if not isinstance(points, list) or len(points) > MAX_POINTS:
        raise PhoneError('경로 좌표 개수를 확인해')
      if data['geometry_status'] == 'full':
        if not v2 and len(points) < 2:
          raise PhoneError('경로 좌표가 부족해')
      elif points:
        raise PhoneError('일부 좌표를 완전한 경로로 보낼 수 없어')
      for point in points:
        if not isinstance(point, list) or len(point) != 2 or not number(point[0], -180, 180) or not number(point[1], -90, 90):
          raise PhoneError('경로 좌표를 확인해')
      active = data['state'] == 'active'
      if not active and (points or (v2 and data['point_count']) or data['matched'] or any(data[k] is not None for k in ('total_m', 'total_s', 'remaining_m', 'remaining_s', 'location_age_ms'))):
        raise PhoneError('중지·재탐색 중에는 이전 경로를 보낼 수 없어')
      if active and (not data['destination'] or data['total_m'] is None or data['total_s'] is None):
        raise PhoneError('안내 경로 요약이 없어')
      if data['matched'] and data['location_age_ms'] is None:
        raise PhoneError('현재 위치 확인이 필요해')
      if not data['matched'] and (data['remaining_m'] is not None or data['remaining_s'] is not None):
        raise PhoneError('경로 위치 미확인 거리는 사용할 수 없어')
      turn = data.get('turn')
      if turn is not None:
        if not v2 or not data['matched'] or not isinstance(turn, dict) or set(turn) != {'code', 'label', 'distance_m'} or not short_text(turn['code'], 80) or not short_text(turn['label'], 30) or not number(turn['distance_m'], 0, 3000000):
          raise PhoneError('회전 안내를 확인해')
      # Same revision may refresh progress, never resurrect/replace its route/state.
      identity = [data[k] for k in ('state', 'destination', 'geometry_status', 'total_m', 'total_s')]
      identity += [data['shape_id'], data['point_count']] if v2 else [points]
      if rev == session.get('route_revision') and identity != session.get('route_identity'):
        raise PhoneError('경로가 변경되면 버전을 올려줘', 'revision', 409)
      if v2:
        shape = session.get('route_shape')
        if data['geometry_status'] != 'full':
          session.pop('route_shape', None)
        elif not shape or shape['id'] != data['shape_id'] or shape['count'] != data['point_count']:
          session['route_shape'] = {'id': data['shape_id'], 'count': data['point_count'], 'points': [],
                                    'hasher': hashlib.sha256(), 'complete': False, 'index': None}
      else:
        session.pop('route_shape', None)
      session.update(route_seq=seq, route_revision=rev, route_identity=copy.deepcopy(identity))
      session.pop('route_challenge', None)
      self.latest = {**copy.deepcopy(data), 'session_id': session['id'], 'received_at': self.clock(),
                     'expires': issued + TTL, 'transit_ms': (self.clock()-issued)*1000, 'geometry': copy.deepcopy(points)}
      return {**self.view(), 'upload': self.upload_view(session)}

  @staticmethod
  def upload_view(session):
    shape = session.get('route_shape')
    if not shape:
      return {'shape_id': '', 'next_offset': 0, 'complete': False}
    return {'shape_id': shape['id'], 'next_offset': len(shape['points']), 'complete': shape['complete']}

  def chunk(self, token, csrf, data):
    with self.service.lock:
      session = self.service.authorize_write(token, csrf, observation=True)
      if not isinstance(data, dict) or set(data) != {'challenge', 'seq', 'revision', 'shape_id', 'offset', 'points'}:
        raise PhoneError('경로 조각 형식을 확인해')
      nonce, issued = session.get('route_challenge', ('', -math.inf))
      if not nonce or data['challenge'] != nonce or not 0 <= self.clock()-issued < TTL:
        raise PhoneError('경로 수신 요청이 만료됐어', 'stale', 409)
      seq = data['seq']
      if type(seq) is not int or not 0 < seq < 2**53 or seq <= session.get('route_seq', 0):
        raise PhoneError('지난 경로 조각이야', 'sequence', 409)
      shape = session.get('route_shape')
      if type(data['revision']) is not int or data['revision'] != session.get('route_revision') or not shape or data['shape_id'] != shape['id']:
        raise PhoneError('경로가 변경됐어', 'revision', 409)
      offset, points = data['offset'], data['points']
      if type(offset) is not int or offset != len(shape['points']) or shape['complete']:
        raise PhoneError('경로 조각 순서를 확인해', 'offset', 409)
      if not isinstance(points, list) or not 1 <= len(points) <= CHUNK_POINTS or offset+len(points) > shape['count']:
        raise PhoneError('경로 조각 크기를 확인해')
      for point in points:
        if not isinstance(point, list) or len(point) != 2 or not number(point[0], -180, 180) or not number(point[1], -90, 90):
          raise PhoneError('경로 좌표를 확인해')
      session['route_seq'] = seq
      session.pop('route_challenge', None)
      # Chunk traffic does not renew the heartbeat or source GPS expiry.
      shape['points'].extend(copy.deepcopy(points))
      for x, y in points:
        shape['hasher'].update(struct.pack('>dd', float(x), float(y)))
      if len(shape['points']) == shape['count']:
        if shape['hasher'].hexdigest() != shape['id']:
          session.pop('route_shape', None)
          raise PhoneError('경로 전체 검증이 맞지 않아', 'digest', 409)
        shape['complete'] = True
        from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.route_hint import RouteShape
        try:
          shape['index'] = RouteShape(shape['points'])
        except ValueError:
          shape['index'] = None
      return {'seq': seq, 'revision': data['revision'], 'upload': self.upload_view(session),
              'scope': 'route_observation', 'control_enabled': False}

  def hint(self, owner, fix):
    from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.route_hint import RouteHint
    with self.service.lock:
      self.service._expire()
      item, now = self.latest, self.clock()
      if not item:
        return RouteHint()
      identity = f"{item['session_id']}:{item['revision']}"
      if item['state'] in ('idle', 'ended'):
        return RouteHint(identity=identity)
      def pending(reason):
        return RouteHint('pending', identity, reason=reason)
      if self.service.mode == 'home_receive':
        return pending('routeHomeMode')
      session = next((s for s in self.service.sessions.values() if s['id'] == item['session_id']), None)
      if not session or owner != item['session_id']:
        return pending('routeOwnerMismatch')
      if item['state'] != 'active':
        return pending('routeNotActive')
      age = item['location_age_ms']
      if not item['matched'] or age is None or not item['received_at'] <= now < item['expires']:
        return pending('routeExpired')
      until = min(item['expires'], item['received_at'] + 3. - (age+item['transit_ms'])/1000.)
      if not now < until:
        return pending('routeExpired')
      shape = session.get('route_shape')
      if not shape or not shape['complete'] or not shape['index']:
        return pending('routeShapePending')
      points, reason = shape['index'].window(fix)
      if not points:
        return pending(reason)
      return RouteHint('active', identity, tuple(points), until)

  def view(self, *, geometry=False):
    with self.service.lock:
      self.service._expire()
      item, now = self.latest, self.clock()
      base = {'received': False, 'state': 'idle', 'reason': '경로 수신 전 또는 만료', 'destination': '',
              'matched': False, 'turn': None, 'remaining_m': None, 'remaining_s': None, 'geometry': [],
              'geometry_status': 'unavailable', 'point_count': 0, 'control_enabled': False,
              'scope': 'route_display_only', 'connection_mode': self.service.mode}
      if not item or item['session_id'] not in {s['id'] for s in self.service.sessions.values()} or not item['received_at'] <= now < item['expires']:
        return base
      session = next(s for s in self.service.sessions.values() if s['id'] == item['session_id'])
      shape = session.get('route_shape') if item.get('protocol') == 2 else None
      points = shape['points'] if shape and shape['complete'] else item['geometry']
      complete = item['geometry_status'] == 'full' and (bool(shape and shape['complete']) if item.get('protocol') == 2 else True)
      age = item['location_age_ms']
      fresh = bool(item['state'] == 'active' and item['matched'] and age is not None and
                   age + item['transit_ms'] + (now-item['received_at'])*1000 < TTL*1000)
      return {**base, 'scope': 'route_observation' if item.get('protocol') == 2 else 'route_display_only', 'received': True, 'seq': item['seq'], 'revision': item['revision'], 'state': item['state'],
              'destination': item['destination'], 'matched': fresh, 'turn': copy.deepcopy(item.get('turn')) if fresh else None,
              'reason': LABELS[item['state']] if item['state'] != 'active' or fresh else '경로 위치 대기 / 만료',
              'total_m': item['total_m'], 'total_s': item['total_s'],
              'remaining_m': item['remaining_m'] if fresh else None, 'remaining_s': item['remaining_s'] if fresh else None,
              'geometry_status': ('full' if complete else 'pending' if item['geometry_status'] == 'full' else item['geometry_status']) if fresh else 'unavailable',
              'point_count': len(points) if fresh and complete else 0,
              'geometry': copy.deepcopy(points) if geometry and fresh and complete else []}
