"""Authenticated TMAP observation cache for connection diagnostics only.

No Params writes, cereal publication, speed target or vehicle control. SDI speed
is an advisory attached to a reported SDI, never a general road speed limit.
"""
import copy
import re
import time
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError


class PhoneNavigation:
  def __init__(self, service, *, clock=time.monotonic):
    self.service, self.clock = service, clock
    self.latest = None
    self.sequences = {}

  def accept(self, token, csrf, data):
    with self.service.lock:
      session = self.service.authorize_write(token, csrf)
      if not isinstance(data, dict) or set(data) - {'stream_id','seq','route_version','route_active','valid','age_ms',
                                                  'sdi_type','sdi_distance_m','sdi_limit_kph','lane_count'}:
        raise PhoneError('올바른 내비 입력이 아니야')
      stream, seq, age = data.get('stream_id'), data.get('seq'), data.get('age_ms')
      if not isinstance(stream,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,64}',stream) or type(seq) is not int or not 0<seq<2**53:
        raise PhoneError('내비 입력 순서를 확인해')
      if type(age) is not int or not 0<=age<2**53 or type(data.get('route_version')) is not int or data['route_version']<0:
        raise PhoneError('내비 입력 시각/경로를 확인해')
      if type(data.get('valid')) is not bool or type(data.get('route_active')) is not bool:
        raise PhoneError('내비 상태를 확인해')
      key = (session['id'],stream)
      # Bound bookkeeping to the currently authorized sessions and one stream
      # per session. An older stream cannot become active again in this session.
      active_ids={s['id'] for s in self.service.sessions.values()}
      self.sequences={k:v for k,v in self.sequences.items() if k[0] in active_ids}
      previous=[k for k in self.sequences if k[0]==session['id']]
      if previous and key not in self.sequences:
        raise PhoneError('내비를 다시 연결하려면 폰 연결을 새로 해', 'stream_changed', 409)
      if seq <= self.sequences.get(key,0):
        raise PhoneError('이미 받았거나 순서가 지난 안내야','sequence',409)
      values={}
      for name, maximum in (('sdi_type',10000),('sdi_distance_m',100000),('sdi_limit_kph',200),('lane_count',20)):
        value=data.get(name)
        if value is not None and (type(value) is not int or not 0<=value<=maximum):
          raise PhoneError('내비 값 범위를 확인해')
        values[name]=value
      self.sequences[key]=seq
      valid=data['valid'] and age<=1500
      self.latest={'session_id':session['id'],'phone':session['name'],'stream_id':stream,'seq':seq,
                   'received':self.clock(),'age_ms':age,'valid':valid,'route_version':data['route_version'],
                   'route_active':data['route_active'], **{k:v if valid else None for k,v in values.items()}}
      return {'received':True,'valid':valid,'scope':'connection_diagnostics_only'}

  def view(self):
    with self.service.lock:
      self.service._expire()
      active_ids={s['id'] for s in self.service.sessions.values()}
      item=self.latest
      if (not item or item['session_id'] not in active_ids or not 0<=self.clock()-item['received']<=2. or
          item['age_ms']+(self.clock()-item['received'])*1000>2000):
        return {'valid':False,'reason':'안내 수신 전 또는 만료','scope':'connection_diagnostics_only'}
      result=copy.deepcopy(item)
      result.pop('session_id');result.pop('received')
      result.update(scope='connection_diagnostics_only', reason='' if item['valid'] else '티맵 안내 미확인')
      return result
