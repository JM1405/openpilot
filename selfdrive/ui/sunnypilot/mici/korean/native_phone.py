"""Native MICI pairing approval. Remote clients cannot approve themselves."""
import pyray as rl

from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError
from openpilot.selfdrive.ui.sunnypilot.mici.korean.settings import SettingsError
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_home import HOME_MODE


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
    text('집 수신' if state['mode'] == HOME_MODE else '연결된 폰' if self.connections else '폰 연결', 215, 10, 21)
    text('모드 ›', 445, 10, 17, (85, 222, 170, 255))
    if self.connections:
      if self.runtime.road_publisher is not None:
        location = service.road_input.view()
        text('폰 경로 ›', 20, 187, 14, (85, 222, 170, 255))
        text('도로 상태 ›', 402, 187, 14, (85, 222, 170, 255))
      else:
        kakao = service.kakao.view()
        text('폰 경로 ›', 20, 187, 14, (85, 222, 170, 255))
        text('카카오 수신 ›', 402, 187, 14, (85, 222, 170, 255))
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
        prompt = '집 테스트 / 수신 전용' if state['home_active'] else state['reason'] if state['mode'] == HOME_MODE else '주차한 뒤 연결 코드를 열어줘'
        text(prompt, 20, 139, 16)
        text('코드 열기', 415, 179, 17, (85, 222, 170, 255))
    text((self.message or ('수신 전용 / 설정·모델·제어 차단' if state['mode'] == HOME_MODE else ''))[:36],
         20, 215, 12, (255, 201, 113, 255))
    text('새 폰 연결' if self.connections else '연결 관리', 425, 215, 14)
    drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))

  def _handle_mouse_release(self, pos):
    x, y = pos.x-self.rect.x, pos.y-self.rect.y
    if x >= 420 and 0 <= y < 40:
      gui_app.push_widget(HomeReceivePage(self.runtime))
      return
    if self.connections and x < 200 and 181 <= y < 208:
      gui_app.push_widget(RouteStatusPage(self.runtime))
      return
    if self.connections and self.runtime.road_publisher is not None and x >= 385 and 181 <= y < 208:
      gui_app.push_widget(RoadStatusPage(self.runtime))
      return
    if self.connections and self.runtime.road_publisher is None and x >= 385 and 181 <= y < 208:
      gui_app.push_widget(KakaoStatusPage(self.runtime))
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


class HomeReceivePage(Widget):
  """Explicit local consent; switching always clears all phone approvals."""
  def __init__(self, runtime):
    super().__init__()
    self.runtime, self.message = runtime, ''
    self.set_rect(rl.Rectangle(0, 0, 536, 240))

  def _render(self, _):
    state = self.runtime.service.mode_view()
    drawing.begin_frame()
    drawing.draw_rectangle(0, 0, 536, 240, drawing.Color(8, 17, 19, 255))
    text('‹ 뒤로', 16, 10, 19)
    text('집 테스트 / 수신 전용', 178, 10, 20)
    text('집 수신 켜짐' if state['home_active'] else '집 수신 중지' if state['mode'] == HOME_MODE else '차량 연결 모드', 20, 49, 19)
    text('폰 연결 / 카카오 자료만 확인해', 20, 80, 17)
    text('설정·모델 변경 / 제어 입력은 차단해', 20, 108, 17)
    text('전환·상태 단절 시 모든 폰 승인을 해제해', 20, 137, 16)
    text('차량 모드로', 20, 177, 19)
    text('집 수신 켜기', 370, 177, 19, (85, 222, 170, 255))
    reason = state['reason'] or ('' if state['home_available'] else self.runtime.home_check())
    text((self.message or reason or '재시작 후에는 다시 켜고 새 코드로 연결해')[:42], 20, 215, 12, (255, 201, 113, 255))
    drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))

  def _handle_mouse_release(self, pos):
    x, y = pos.x-self.rect.x, pos.y-self.rect.y
    if x < 110 and y < 40:
      self.dismiss()
    elif 168 <= y < 208 and (x < 185 or x >= 345):
      try:
        self.runtime.service.device_set_home(x >= 345)
        self.message = '전환했어. 뒤로 가서 새 연결 코드를 열어줘'
      except (PhoneError, SettingsError) as exc:
        self.message = str(exc)


class KakaoStatusPage(Widget):
  def __init__(self, runtime):
    super().__init__()
    self.runtime = runtime
    self.set_rect(rl.Rectangle(0, 0, 536, 240))

  def _render(self, _):
    state = self.runtime.service.kakao.view()
    drawing.begin_frame()
    drawing.draw_rectangle(0, 0, 536, 240, drawing.Color(8, 17, 19, 255))
    text('‹ 뒤로', 16, 10, 19)
    home = self.runtime.service.mode == HOME_MODE
    text('집 테스트 / 카카오 수신' if home else '카카오 수신', 175 if home else 215, 10, 20)
    text(state['reason'], 20, 49, 16)
    counts = {kind: sum(e['kind'] == kind for e in state['events']) for kind in ('camera', 'section', 'bump', 'sharp_turn')}
    text(f"단속 {counts['camera']} / 구간 {counts['section']} / 방지턱 {counts['bump']} / 급커브 {counts['sharp_turn']}", 20, 84, 16)
    text('GPS 유효' if state['location_fresh'] else 'GPS 대기 / 만료', 20, 119, 16)
    text('전방 도로 / 코너 속도 확인 전', 20, 154, 16)
    text('수신 확인용 / 자동 감속 연결 안 됨', 20, 204, 15, (255, 201, 113, 255))
    drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))

  def _handle_mouse_release(self, pos):
    if pos.x-self.rect.x < 110 and pos.y-self.rect.y < 40:
      self.dismiss()


class RouteStatusPage(Widget):
  def __init__(self, runtime):
    super().__init__()
    self.runtime = runtime
    self.set_rect(rl.Rectangle(0, 0, 536, 240))

  def _render(self, _):
    state = self.runtime.service.route.view()
    drawing.begin_frame()
    drawing.draw_rectangle(0, 0, 536, 240, drawing.Color(8, 17, 19, 255))
    text('‹ 뒤로', 16, 10, 19)
    text('폰 경로', 220, 10, 21)
    text(state['destination'][:26] or '목적지 대기', 20, 54, 21)
    text(state['reason'], 20, 91, 17)
    if state['remaining_m'] is not None and state['remaining_s'] is not None:
      text(f"{state['remaining_m']/1000:.1f} km / {(state['remaining_s']+59)//60:.0f}분", 20, 127, 20)
    turn = state.get('turn')
    if turn:
      dist = f"{turn['distance_m']/1000:.1f} km" if turn['distance_m'] >= 1000 else f"{turn['distance_m']:.0f} m"
      text(f"{dist} / {turn['label']}", 20, 166, 20, (85, 222, 170, 255))
    else:
      text(f"경로 좌표 {state['point_count']}개" if state['point_count'] else '경로 형상 대기 / 보류', 20, 166, 15)
    text('표시 전용 / 차량 제어 미적용', 20, 212, 14, (255, 201, 113, 255))
    drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))

  def _handle_mouse_release(self, pos):
    if pos.x-self.rect.x < 110 and pos.y-self.rect.y < 40:
      self.dismiss()


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
