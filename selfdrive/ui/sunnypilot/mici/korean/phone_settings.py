"""Transport-independent pairing and setting-request service.

Device-side methods must only be exposed to a trusted local approval surface.
The PC adapter is a loopback demo; this module starts no network or vehicle work.
"""
import hashlib
import hmac
import json
import re
import secrets
import threading
import time

from openpilot.selfdrive.ui.sunnypilot.mici.korean.settings import SettingsError

CODE_TTL = 120
SESSION_TTL = 1800
MAX_ATTEMPTS = 5
MAX_SESSIONS = 3
MAX_REQUESTS = 64


class PhoneError(ValueError):
  def __init__(self, message, code='invalid', status=400):
    super().__init__(message)
    self.code, self.status = code, status


def digest(value):
  return hashlib.sha256(value.encode()).hexdigest() if isinstance(value, str) else ''


class PhoneSettings:
  def __init__(self, controller, *, clock=time.monotonic):
    self.controller, self.clock = controller, clock
    self.lock = threading.RLock()
    self.window = None
    self.pending = None
    self.sessions = {}

  def _expire(self):
    now = self.clock()
    if self.window and now >= self.window['expires']:
      self.window = None
    if self.pending and now >= self.pending['expires']:
      self.pending = None
    self.sessions = {key: s for key, s in self.sessions.items() if now < s['expires']}

  def _parked(self):
    view = self.controller.view()
    if not view['parked']:
      raise PhoneError(view['reason'], 'blocked', 422)

  def device_open(self):
    with self.lock:
      self._expire()
      self._parked()
      if len(self.sessions) >= MAX_SESSIONS:
        raise PhoneError('연결된 폰을 해제한 뒤 새로 연결해', 'capacity', 409)
      self.pending = None
      self.window = {'code': f'{secrets.randbelow(1000000):06d}', 'expires': self.clock() + CODE_TTL, 'attempts': 0}
      return self.device_view()

  def device_view(self):
    with self.lock:
      self._expire()
      window = None
      if self.window:
        window = {'code': self.window['code'], 'remaining': max(0, int(self.window['expires'] - self.clock())),
                  'attempts_left': MAX_ATTEMPTS - self.window['attempts']}
      pending = None
      if self.pending:
        pending = {k: self.pending[k] for k in ('id', 'name', 'state')}
      return {'window': window, 'pending': pending,
              'sessions': [{'id': s['id'], 'name': s['name'], 'remaining': max(0, int(s['expires'] - self.clock()))}
                           for s in self.sessions.values()]}

  def pair(self, code, name):
    with self.lock:
      self._expire()
      if not isinstance(name, str) or not 1 <= len(name.strip()) <= 24 or any(ord(c) < 32 for c in name):
        raise PhoneError('폰 이름을 1~24자로 입력해')
      if not self.window:
        raise PhoneError('기기에서 새 연결 코드를 열어줘', 'pair_closed', 410)
      if self.window['attempts'] >= MAX_ATTEMPTS:
        raise PhoneError('입력 횟수를 초과했어. 기기에서 새 코드를 열어줘', 'attempts', 429)
      if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code) or not hmac.compare_digest(code, self.window['code']):
        self.window['attempts'] += 1
        raise PhoneError('연결 코드를 다시 확인해', 'wrong_code', 403)
      self._parked()
      token = secrets.token_urlsafe(32)
      self.pending = {'id': secrets.token_hex(8), 'name': name.strip(), 'state': 'pending',
                      'token': digest(token), 'expires': self.clock() + CODE_TTL}
      self.window = None  # consume once, before device approval
      return token

  def device_decide(self, pending_id, approved):
    with self.lock:
      self._expire()
      if not self.pending or pending_id != self.pending['id'] or self.pending['state'] != 'pending':
        raise PhoneError('대기 중인 연결 요청을 다시 확인해', 'missing', 404)
      if type(approved) is not bool:
        raise PhoneError('올바른 승인 값이 아니야')
      if approved:
        self._parked()  # a parked check on opening the code is not enough
      self.pending['state'] = 'approved' if approved else 'rejected'
      return self.device_view()

  def session(self, token):
    with self.lock:
      self._expire()
      key = digest(token)
      if not key or key not in self.sessions:
        raise PhoneError('연결이 없거나 만료됐어. 기기에서 다시 연결해', 'unauthorized', 401)
      return self.sessions[key]

  def status(self, token):
    """Return public state plus an optional replacement cookie after approval."""
    with self.lock:
      self._expire()
      if self.pending and hmac.compare_digest(digest(token), self.pending['token']):
        pending = self.pending
        if pending['state'] != 'approved':
          return {'state': pending['state'], 'name': pending['name']}, None
        self._parked()
        if len(self.sessions) >= MAX_SESSIONS:
          raise PhoneError('연결 가능한 폰 수를 초과했어', 'capacity', 409)
        replacement = secrets.token_urlsafe(32)
        self.sessions[digest(replacement)] = {'id': secrets.token_hex(8), 'name': pending['name'],
                                             'csrf': secrets.token_urlsafe(32), 'expires': self.clock() + SESSION_TTL,
                                             'requests': {}}
        self.pending = None  # old unauthenticated ticket cannot be reused
        token = replacement
      else:
        replacement = None
      session = self.session(token)
      return {'state': 'connected', 'name': session['name'], 'csrf': session['csrf'],
              'session_id': session['id'], 'remaining': max(0, int(session['expires'] - self.clock()))}, replacement

  def authorize_write(self, token, csrf):
    session = self.session(token)
    if not isinstance(csrf, str) or not hmac.compare_digest(digest(csrf), digest(session['csrf'])):
      raise PhoneError('연결을 다시 확인한 뒤 요청해', 'csrf', 403)
    return session

  def disconnect(self, token):
    with self.lock:
      self.sessions.pop(digest(token), None)
      if self.pending and hmac.compare_digest(digest(token), self.pending['token']):
        self.pending = None

  def device_revoke(self, session_id):
    with self.lock:
      self._expire()
      keys = [key for key, s in self.sessions.items() if s['id'] == session_id]
      if not keys:
        raise PhoneError('이미 연결이 해제됐어', 'missing', 404)
      del self.sessions[keys[0]]

  def view(self, token):
    with self.lock:
      self.session(token)
      return self.controller.view()

  def change(self, token, csrf, request):
    with self.lock:
      session = self.authorize_write(token, csrf)
      if not isinstance(request, dict) or set(request) != {'request_id', 'id', 'value', 'revision', 'acknowledged'}:
        raise PhoneError('올바른 변경 요청이 아니야')
      request_id = request['request_id']
      if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,64}', request_id):
        raise PhoneError('올바른 요청 번호가 아니야')
      fingerprint = digest(json.dumps(request, sort_keys=True, ensure_ascii=True))
      records = session['requests']
      if request_id in records:
        if records[request_id]['fingerprint'] != fingerprint:
          raise PhoneError('같은 요청 번호에 다른 변경을 보낼 수 없어', 'request_conflict', 409)
        return dict(records[request_id]['receipt'])  # no second write, including failed/uncertain requests
      if len(records) >= MAX_REQUESTS:
        raise PhoneError('이 연결의 요청 한도에 도달했어. 연결을 새로 해줘', 'capacity', 429)
      receipt = {'request_id': request_id, 'id': request['id'], 'value': request['value']}
      try:
        self.controller.save(request['id'], request['value'], request['revision'], acknowledged=request['acknowledged'] is True)
        receipt.update(outcome='saved', message='저장값을 확인했어. 현재 반영 상태는 따로 확인해.')
      except SettingsError as exc:
        receipt.update(outcome='unknown' if exc.code == 'storage' else 'rejected', code=exc.code, message=str(exc))
      records[request_id] = {'fingerprint': fingerprint, 'receipt': receipt}
      return dict(receipt)

  def result(self, token, request_id):
    with self.lock:
      session = self.session(token)
      record = session['requests'].get(request_id)
      if not record:
        raise PhoneError('이 연결에서 받은 요청을 찾지 못했어. 현재 저장값을 확인해', 'missing', 404)
      receipt = dict(record['receipt'])
      view = self.controller.view()
      row = next((r for r in view['rows'] if r['id'] == receipt['id']), None)
      return {'receipt': receipt, 'setting': row,
              'superseded': bool(row and receipt['outcome'] == 'saved' and row['saved'] != receipt['value'])}
