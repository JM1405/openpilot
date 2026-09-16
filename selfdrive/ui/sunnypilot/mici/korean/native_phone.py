"""Native MICI pairing approval. Remote clients cannot approve themselves."""
import pyray as rl

from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError
from openpilot.selfdrive.ui.sunnypilot.mici.korean.settings import SettingsError


def text(value, x, y, size=16, color=(243, 248, 246, 255)):
  drawing.alert_text(str(value).replace('·', '/'), x, y+size, size, drawing.Color(*color), size)


class KoreanPhonePage(Widget):
  def __init__(self, runtime):
    super().__init__()
    self.runtime = runtime
    self.message = ''
    self.connections = False
    self.displayed_pending = None
    self.displayed_sessions = []
    self.set_rect(rl.Rectangle(0, 0, 536, 240))

  def _render(self, _):
    service = self.runtime.service
    state = service.device_view()
    self.displayed_pending = state['pending']['id'] if state['pending'] and state['pending']['state'] == 'pending' else None
    self.displayed_sessions = [session['id'] for session in state['sessions']]
    drawing.begin_frame()
    drawing.draw_rectangle(0, 0, 536, 240, drawing.Color(8, 17, 19, 255))
    text('‹ 뒤로', 16, 10, 19)
    text('연결된 폰' if self.connections else '폰 연결', 215, 10, 21)
    if self.connections:
      from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.runtime import enabled as road_input_enabled
      if road_input_enabled():
        location = service.road_input.view()
        text('GPS 위치 수신' if location['valid'] else 'GPS 위치 입력 대기', 20, 187, 14)
        text('도로 상태 ›', 402, 187, 14, (85, 222, 170, 255))
      else:
        nav = service.navigation.view()
        text('티맵 안내 수신' if nav['valid'] else '티맵 안내 미확인', 20, 187, 14)
      if not state['sessions']:
        text('연결된 폰이 없어', 20, 83, 20)
      for i, session in enumerate(state['sessions']):
        text(session['name'][:14], 20, 53+i*43, 15)
        if len(session['name']) > 14:
          text(session['name'][14:], 20, 71+i*43, 12)
        text(f"{session['remaining']//60}분 남음", 280, 53+i*43, 14)
        text('해제', 458, 53+i*43, 17, (255, 201, 113, 255))
    elif self.runtime.transport is None:
      text('폰 연결 주소를 준비 중이야', 20, 76, 21)
      text(self.runtime.network_error or '기기에 암호화 연결 설정이 필요해', 20, 118, 15)
    else:
      transport = self.runtime.transport
      text(transport.url[:60], 20, 44, 14)
      text('폰에서 아래 기기 인증값을 확인해', 20, 69, 12)
      text(transport.fingerprint[:32], 20, 87, 12)
      text(transport.fingerprint[32:], 20, 104, 12)
      pending = state['pending']
      if pending and pending['state'] == 'pending':
        text(pending['name'], 20, 132, 17)
        text('이 폰의 연결 요청', 20, 153, 13)
        text('거절', 278, 177, 20)
        text('승인', 434, 177, 20, (85, 222, 170, 255))
      elif state['window']:
        text(state['window']['code'], 20, 133, 34, (85, 222, 170, 255))
        text(f"{state['window']['remaining']}초 남음", 230, 145, 15)
        text('새 코드', 425, 179, 17)
      else:
        text('주차한 뒤 연결 코드를 열어줘', 20, 139, 18)
        text('코드 열기', 415, 179, 17, (85, 222, 170, 255))
    text(self.message[:36], 20, 215, 12, (255, 201, 113, 255))
    text('새 폰 연결' if self.connections else '연결 관리', 425, 215, 14)
    drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))

  def _handle_mouse_release(self, pos):
    x, y = pos.x-self.rect.x, pos.y-self.rect.y
    if self.connections and x >= 385 and 181 <= y < 208:
      from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.runtime import enabled
      if enabled():
        gui_app.push_widget(RoadStatusPage(self.runtime))
        return
    if x<110 and y<40:
      self.dismiss()
      return
    if x>=415 and y>=209:
      self.connections = not self.connections
      self.displayed_pending, self.displayed_sessions = None, []
      self.message = ''
      return
    service = self.runtime.service
    try:
      # Bind taps to the last rendered identity, not a newly arrived request.
      with service.lock:
        state = service.device_view()
        if self.connections:
          for i, session_id in enumerate(self.displayed_sessions):
            if x>=435 and 48+i*43<=y<88+i*43:
              service.device_revoke(session_id)
              self.message = '폰 연결 권한을 해제했어'
              return
        elif self.runtime.transport is not None and 170<=y<206:
          if self.displayed_pending:
            if x>=415 or 255<=x<350:
              service.device_decide(self.displayed_pending, x>=415)
              self.message = '연결을 승인했어' if x>=415 else '연결을 거절했어'
          elif x>=400 and not state['pending']:
            service.device_open()
            self.message = ''
    except (PhoneError, SettingsError) as exc:
      self.message = str(exc)


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
    text('연결 승인 / 권한 해제', 28, 89, 21, (85, 222, 170, 255))
    text('주차한 뒤 설정을 바꿀 수 있어', 28, 134, 18)
    drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))
