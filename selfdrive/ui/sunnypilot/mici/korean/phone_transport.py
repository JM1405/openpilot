"""Phone-only HTTPS transport. Approval exists only on the native device UI."""
import hashlib
import json
import ssl
import threading
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError, SESSION_TTL, digest
from openpilot.selfdrive.ui.sunnypilot.mici.korean.settings import SettingsError

COOKIE = '__Secure-korean_phone'


class PhoneHandler(BaseHTTPRequestHandler):
  protocol_version = 'HTTP/1.0'

  def setup(self):
    self.request.settimeout(3.)
    super().setup()

  def log_message(self, *_):
    pass  # Never record pairing credentials, cookies, or setting requests.

  def token(self):
    try:
      cookie = SimpleCookie(self.headers.get('Cookie', ''))
      return cookie[COOKIE].value if COOKIE in cookie else ''
    except CookieError:
      return ''

  def respond(self, payload, status=200, cookie=None):
    body = json.dumps(payload, ensure_ascii=False).encode()
    self.send_response(status)
    for key, value in {'Content-Type': 'application/json; charset=utf-8', 'Content-Length': str(len(body)),
                       'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                       'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'"}.items():
      self.send_header(key, value)
    if cookie is not None:
      age = SESSION_TTL if cookie else 0
      self.send_header('Set-Cookie', f'{COOKIE}={cookie}; Path=/api/phone/; Secure; HttpOnly; SameSite=Strict; Max-Age={age}')
    self.end_headers()
    try:
      self.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
      pass

  def dispatch(self, write=False):
    if self.headers.get_all('Host', []) != [self.server.authority]:
      return self.respond({'error': 'Invalid host', 'code': 'host'}, 403)
    if write and self.headers.get_all('Origin', []) != [f'https://{self.server.authority}']:
      return self.respond({'error': '같은 연결에서 요청해', 'code': 'origin'}, 403)
    service = self.server.service
    try:
      data = None
      if write:
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or self.headers.get('Transfer-Encoding'):
          raise ValueError('length')
        length = int(lengths[0])
        if not 0 < length <= 4096 or self.headers.get('Content-Type') != 'application/json':
          raise ValueError('body')
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
          raise ValueError('body')
      def response(payload, status=200, cookie=None):
        return payload, status, cookie

      def route():
        token = self.token()
        if not write:
          if self.path == '/api/phone/session':
            state, replacement = service.status(token)
            return response(state, cookie=replacement)
          if self.path == '/api/phone/settings':
            return response(service.view(token))
          if self.path == '/api/phone/navigation':
            service.session(token)
            return response(service.navigation.view())
          if self.path == '/api/phone/road':
            service.session(token)
            return response(service.road_input.view())
          if self.path == '/api/phone/road/status':
            service.session(token)
            return response(service.road_status.view())
          if self.path.startswith('/api/phone/changes/'):
            return response(service.result(token, self.path.rsplit('/', 1)[1]))
        else:
          if self.path == '/api/phone/pair':
            if digest(token) in service.sessions:
              raise PhoneError('먼저 연결을 해제해', 'connected', 409)
            return response({'state': 'pending'}, cookie=service.pair(data.get('code'), data.get('name')))
          if self.path == '/api/phone/cancel':
            if digest(token) in service.sessions:
              raise PhoneError('연결 해제를 사용해', 'connected', 409)
            service.disconnect(token)
            return response({'state': 'disconnected'}, cookie='')
          if self.path == '/api/phone/logout':
            service.authorize_write(token, self.headers.get('X-CSRF-Token'))
            service.disconnect(token)
            return response({'state': 'disconnected'}, cookie='')
          if self.path == '/api/phone/changes':
            return response(service.change(token, self.headers.get('X-CSRF-Token'), data))
          if self.path == '/api/phone/navigation':
            return response(service.navigation.accept(token, self.headers.get('X-CSRF-Token'), data))
          if self.path in ('/api/phone/road/sync', '/api/phone/road/commit', '/api/phone/road/fix', '/api/phone/road/stop'):
            return response(service.road_input.accept(token, self.headers.get('X-CSRF-Token'), self.path.rsplit('/', 1)[1], data))
        return response({'error': 'Not found'}, 404)
      with service.lock:
        payload, status, cookie = route()
      # Socket writes must not hold the native UI/service lock.
      return self.respond(payload, status, cookie)
    except PhoneError as exc:
      return self.respond({'error': str(exc), 'code': exc.code}, exc.status)
    except SettingsError as exc:
      return self.respond({'error': str(exc), 'code': exc.code}, 500 if exc.code == 'storage' else 422)
    except (ValueError, TypeError, UnicodeDecodeError):
      return self.respond({'error': '올바른 요청 본문이 아니야', 'code': 'invalid'}, 400)

  def do_GET(self):
    self.dispatch()

  def do_POST(self):
    self.dispatch(True)


class PhoneServer(ThreadingHTTPServer):
  daemon_threads = True
  allow_reuse_address = False

  def __init__(self, address, service, authority):
    self.service, self.authority = service, authority
    self.slots = threading.BoundedSemaphore(8)
    super().__init__(address, PhoneHandler)

  def process_request(self, request, client_address):
    if not self.slots.acquire(blocking=False):
      self.shutdown_request(request)
      return
    try:
      super().process_request(request, client_address)
    except BaseException:
      self.slots.release()
      raise

  def process_request_thread(self, request, client_address):
    try:
      super().process_request_thread(request, client_address)
    finally:
      self.slots.release()


class PhoneTransport:
  def __init__(self, service, *, host, port, authority, certfile, keyfile):
    if not authority or any(c in authority for c in '/\\\r\n @'):
      raise ValueError('exact HTTPS authority required')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile, keyfile)
    with open(certfile) as certificate:
      self.fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate.read())).hexdigest()
    self.server = PhoneServer((host, port), service, authority)
    try:
      self.server.socket = context.wrap_socket(self.server.socket, server_side=True, do_handshake_on_connect=False)
    except BaseException:
      self.server.server_close()
      raise
    self.url = f'https://{authority}'
    self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .1}, daemon=True, name='korean-phone-https')
    self.thread.start()
    self.closed = False

  def close(self):
    if not self.closed:
      self.server.shutdown()
      self.server.server_close()
      self.thread.join(timeout=2)
      self.closed = True
