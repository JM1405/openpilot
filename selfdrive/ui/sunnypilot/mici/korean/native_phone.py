"""Large local pairing controls. QR transports the pin; C4 still grants approval."""
import pyray as rl
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError
from openpilot.selfdrive.ui.sunnypilot.mici.korean.settings import SettingsError
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_home import HOME_MODE
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_pairing import pairing_payload, qr_tiles

BG = drawing.Color(8, 17, 19, 255)
WHITE = drawing.Color(243, 248, 246, 255)
GREEN = drawing.Color(85, 222, 170, 255)


def text(value, x, y, size=24, color=WHITE):
  drawing.alert_text(str(value).replace('·', '/'), x, y+size, size, drawing.Color(*color), size)


def button(value, rect, active=False):
  drawing.draw_rectangle_rounded(drawing.Rectangle(*rect), .18, 6,
                                drawing.Color(29, 96, 75, 255) if active else drawing.Color(28, 46, 48, 255))
  text(value, rect[0]+14, rect[1]+(rect[3]-26)//2, 26)


def lines(value, y=82):
  value = str(value)
  for i in range(2):
    text(value[i*21:(i+1)*21], 16, y+i*32, 24)


class KoreanPhonePage(Widget):
  def __init__(self, runtime):
    super().__init__()
    self.runtime, self.message = runtime, ''
    self.connections, self.show_qr, self.selected = False, False, 0
    self.displayed_pending = None
    self.displayed_sessions = []
    self.actions = []
    self.qr_payload, self.qr_rects = None, []
    self.set_rect(rl.Rectangle(0, 0, 536, 240))

  def action(self, key, label, rect, active=False):
    button(label, rect, active)
    self.actions.append((key, rect))

  def _render(self, _):
    state = self.runtime.service.device_view()
    pending = state['pending']
    self.displayed_pending = pending['id'] if pending and pending['state'] == 'pending' else None
    self.displayed_sessions, self.actions = [], []
    drawing.begin_frame()
    drawing.draw_rectangle(0, 0, 536, 240, BG)
    self.action('back', '뒤로', (16, 8, 112, 48))
    if self.displayed_pending:
      self.show_qr = False
      text('연결 요청', 166, 17, 28)
      text(pending['name'][:18], 16, 78, 28)
      text('내 폰이 맞으면 승인해줘', 16, 117, 24)
      self.action('deny', '거절', (16, 170, 244, 58))
      self.action('approve', '승인', (276, 170, 244, 58), True)
    elif self.connections:
      text('연결된 폰', 146, 17, 28)
      sessions = state['sessions']
      if sessions:
        self.selected %= len(sessions)
        item = sessions[self.selected]
        self.displayed_sessions = [item['id']]
        if len(sessions) > 1:
          self.action('next', f'{self.selected+1}/{len(sessions)} 다음', (354, 8, 166, 48))
        text(item['name'][:12], 16, 85, 28)
        self.action('revoke', '연결 해제', (352, 76, 168, 58))
      else:
        text('폰에서 연결 확인 중' if pending and pending['state'] == 'approved' else '연결된 폰이 없어', 16, 88, 28)
      self.action('route', '폰 경로', (16, 170, 244, 58))
      self.action('receipt', '수신 상태', (276, 170, 244, 58))
    elif self.show_qr and state['window'] and self.runtime.transport:
      transport = self.runtime.transport
      try:
        payload = pairing_payload(transport.url, transport.fingerprint, state['window']['code'])
        if payload != self.qr_payload:
          self.qr_rects = qr_tiles(payload)
          self.qr_payload = payload
        text('폰으로 QR 스캔', 16, 76, 28)
        text(f"남은 시간 {state['window']['remaining']}초", 16, 118, 24)
        self.action('open', 'QR 새로 만들기', (16, 170, 264, 58))
        drawing.draw_rectangle(304, 12, 216, 216, drawing.WHITE)
        for rect in self.qr_rects:
          drawing.draw_rectangle(*rect, drawing.BLACK)
      except (ValueError, ImportError):
        self.show_qr = False
        self.message = 'QR을 만들지 못했어. 다시 시도해줘'
        lines(self.message)
    else:
      expired = self.show_qr
      self.show_qr, self.qr_payload, self.qr_rects = False, None, []
      text('폰 연결', 162, 17, 28)
      self.action('mode', '집 모드', (368, 8, 152, 48))
      if self.runtime.transport is None:
        text('Wi-Fi 연결을 확인해줘', 16, 79, 28)
        text('주소 준비가 아직 안 됐어', 16, 119, 24)
        self.action('retry', '다시 확인', (16, 170, 504, 58), True)
      elif self.message:
        lines(self.message, 78)
        self.action('clear', '확인', (16, 170, 504, 58), True)
      else:
        self.action('open', 'QR 다시 열기' if expired else 'QR로 폰 연결', (16, 76, 504, 66), True)
        self.action('connections', f"연결된 폰 {len(state['sessions'])}대", (16, 166, 504, 62))
    drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))

  def _handle_mouse_release(self, pos):
    x, y = pos.x-self.rect.x, pos.y-self.rect.y
    action = next((key for key, (ax, ay, w, h) in self.actions if ax <= x < ax+w and ay <= y < ay+h), None)
    service = self.runtime.service
    try:
      if action == 'back':
        if self.connections or self.show_qr or self.message:
          self.connections, self.show_qr, self.message = False, False, ''
        else:
          self.dismiss()
      elif action == 'mode':
        gui_app.push_widget(HomeReceivePage(self.runtime))
      elif action == 'connections':
        self.connections = True
      elif action == 'next':
        self.selected += 1
      elif action == 'clear':
        self.message = ''
      elif action == 'route':
        gui_app.push_widget(RouteStatusPage(self.runtime))
      elif action == 'receipt':
        gui_app.push_widget(RoadStatusPage(self.runtime) if self.runtime.road_publisher is not None else KakaoStatusPage(self.runtime))
      elif action == 'retry':
        self.runtime.retry_local_transport()
      elif action in ('approve', 'deny') and self.displayed_pending:
        service.device_decide(self.displayed_pending, action == 'approve')
        self.connections = action == 'approve'
      elif action == 'revoke' and self.displayed_sessions:
        service.device_revoke(self.displayed_sessions[0])
      elif action == 'open':
        with service.lock:
          # Never replace a request that arrived after the frame was rendered.
          if not service.device_view()['pending']:
            service.device_open()
            self.show_qr, self.message = True, ''
    except (PhoneError, SettingsError) as exc:
      self.message, self.show_qr = str(exc), False
    self.actions = []  # require another rendered frame before another action


class HomeReceivePage(Widget):
  """Explicit local consent; switching clears approvals as before."""
  def __init__(self, runtime):
    super().__init__()
    self.runtime, self.message, self.actions = runtime, '', []
    self.set_rect(rl.Rectangle(0, 0, 536, 240))

  def _render(self, _):
    state = self.runtime.service.mode_view()
    drawing.begin_frame()
    drawing.draw_rectangle(0, 0, 536, 240, BG)
    button('뒤로', (16, 8, 112, 48))
    text('집 수신 설정', 164, 17, 28)
    text('집 수신 켜짐' if state['home_active'] else '집 수신 중지' if state['mode'] == HOME_MODE else '차량 연결 모드', 16, 76, 30, GREEN)
    text('수신 전용 / 설정 변경 없음', 16, 120, 24)
    self.actions = [('back', (16, 8, 112, 48))]
    if self.message:
      drawing.draw_rectangle(0, 65, 536, 98, BG)
      lines(self.message, 76)
      button('확인', (16, 170, 504, 58), True)
      self.actions.append(('clear', (16, 170, 504, 58)))
    else:
      button('차량 모드', (16, 170, 244, 58))
      button('집 수신 켜기', (276, 170, 244, 58), True)
      self.actions.extend([('vehicle', (16, 170, 244, 58)), ('home', (276, 170, 244, 58))])
    drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))

  def _handle_mouse_release(self, pos):
    x, y = pos.x-self.rect.x, pos.y-self.rect.y
    action = next((k for k, (ax, ay, w, h) in self.actions if ax <= x < ax+w and ay <= y < ay+h), None)
    if action == 'back':
      self.dismiss()
    elif action == 'clear':
      self.message = ''
    elif action in ('home', 'vehicle'):
      try:
        self.runtime.service.device_set_home(action == 'home')
        self.dismiss()
      except (PhoneError, SettingsError) as exc:
        self.message = str(exc)
    self.actions = []


class RoadStatusPage(Widget):
  def __init__(self, runtime):
    super().__init__()
    self.runtime = runtime
    self.set_rect(rl.Rectangle(0, 0, 536, 240))

  def _render(self, _):
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.road_status import describe
    service = self.runtime.service
    lines = describe(service.road_status.view(), service.road_input.view()['valid'])
    drawing.begin_frame()
    drawing.draw_rectangle(0, 0, 536, 240, drawing.Color(8, 17, 19, 255))
    text('‹ 뒤로', 16, 10, 19)
    text('도로 입력 상태', 204, 10, 21)
    for i, line in enumerate(lines):
      text(line, 20, 49 + i * 29, 16)
    text('주행 보조 상태는 주행 화면에서 확인해', 20, 215, 13, (155, 173, 167, 255))
    drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))

  def _handle_mouse_release(self, pos):
    if pos.x-self.rect.x < 110 and pos.y-self.rect.y < 40:
      self.dismiss()


class KoreanPhoneButton(Widget):
  def __init__(self, runtime):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 402, 180))
    self.set_click_callback(lambda: gui_app.push_widget(KoreanPhonePage(runtime)))

  def _render(self, _):
    drawing.begin_frame()
    drawing.draw_rectangle_rounded(drawing.Rectangle(0, 0, 402, 180), .15, 6, drawing.Color(24, 43, 40, 255))
    text('폰 연결', 28, 28, 36)
    text('QR로 연결 / 기기에서 승인', 28, 89, 24, (85, 222, 170, 255))
    text('같은 Wi-Fi에서 연결해', 28, 134, 24)
    drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))
