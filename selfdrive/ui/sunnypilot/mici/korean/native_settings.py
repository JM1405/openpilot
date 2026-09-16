"""536x240 Korean settings connected to existing Params and current SubMaster."""
import atexit
import os
import time
import pyray as rl

from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import SettingsLayoutSP
from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing
from openpilot.selfdrive.ui.sunnypilot.mici.korean.settings import SettingsController, SettingsError, SETTINGS, observed

WHITE = drawing.Color(243, 248, 246, 255)
DIM = drawing.Color(155, 173, 167, 255)
GREEN = drawing.Color(85, 222, 170, 255)
AMBER = drawing.Color(255, 201, 113, 255)


def label(value, x, y, size=17, color=WHITE):
  # The bundled alert font omits these two symbols. Use supported glyphs
  # instead of relying on a browser/system font fallback on the device.
  text = str(value).replace('·', '/').replace('→', '>')
  drawing.alert_text(text, x, y + size, size, color, size)


def panel(x, y, w, h, color):
  drawing.draw_rectangle_rounded(drawing.Rectangle(x, y, w, h), .15, 6, color)


class KoreanSettingsPage(Widget):
  def __init__(self, controller=None):
    super().__init__()
    self.controller = controller or SettingsController(ui_state.params, lambda: observed(
      ui_state.sm, time.monotonic(), ui_state.started_frame, release=ui_state.is_release or ui_state.is_sp_release))
    self.selected = 0
    self.draft = None
    self.confirming = False
    self.message = ''
    self.set_rect(rl.Rectangle(0, 0, 536, 240))

  def show_event(self):
    super().show_event()
    self.draft, self.confirming, self.message = None, False, ''

  def _render(self, _):
    try:
      view = self.controller.view()
    except SettingsError as exc:
      drawing.begin_frame()
      drawing.draw_rectangle(0, 0, 536, 240, drawing.Color(8, 17, 19, 255))
      label('‹ 뒤로', 16, 10, 19)
      label(str(exc), 20, 100, 18, AMBER)
      drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))
      return
    row = view['rows'][self.selected]
    drawing.begin_frame()
    drawing.draw_rectangle(0, 0, 536, 240, drawing.Color(8, 17, 19, 255))
    label('‹ 뒤로', 16, 10, 19)
    label('주행 설정' if not self.confirming else '변경 내용 확인', 202, 10, 21)
    if self.confirming:
      spec = SETTINGS[self.draft[0]]
      label(spec['title'] + ' → ' + spec['options'][int(self.draft[1])], 20, 48, 20, GREEN)
      lines = []
      for text in row['notices'][int(self.draft[1])]:
        # This small fixed notice set is wrapped for the MICI screen. No
        # dependency on PC-only Pillow or the global language setting.
        while text:
          lines.append(text[:34])
          text = text[34:]
      for i, text in enumerate(lines):
        label(text, 20, 80 + i * 21, 14)
      label(self.message or '저장 직전 주차 상태를 다시 확인해', 20, 207, 13, AMBER)
      panel(404, 197, 112, 34, drawing.Color(29, 96, 75, 255))
      label('확인·저장', 415, 205, 17)
    else:
      for i, item in enumerate(view['rows']):
        panel(16 + i * 172, 44, 160, 33, drawing.Color(32, 77, 65, 255) if i == self.selected else drawing.Color(24, 36, 39, 255))
        label(item['title'], 24 + i * 172, 51, 15)
      def value(value):
        return row['options'][int(value)] if type(value) is bool else '확인 불가'
      label('저장된 선택', 20, 91, 13, DIM)
      label(value(row['saved']), 20, 111, 23)
      label('현재 확인된 설정', 280, 91, 13, DIM)
      label(value(row['current']), 280, 111, 23, GREEN if row['current'] is not None else DIM)
      label(row['status'], 20, 143, 14, AMBER)
      for i, option in enumerate(row['options']):
        selected = self.draft is not None and self.draft[1] == bool(i)
        panel(20 + i * 192, 166, 180, 32, drawing.Color(29, 96, 75, 255) if selected else drawing.Color(30, 45, 49, 255))
        label(option, 32 + i * 192, 173, 16, WHITE if row['editable'] else DIM)
      panel(404, 166, 112, 32, drawing.Color(29, 96, 75, 255) if self.draft else drawing.Color(30, 45, 49, 255))
      label('변경 확인', 415, 173, 16, WHITE if self.draft else DIM)
      label(self.message or row['blocked_reason'] or 'P단 · 보조 해제 확인', 20, 214, 13, AMBER if self.message or not row['editable'] else DIM)
    drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))

  def _handle_mouse_release(self, pos):
    x, y = pos.x - self.rect.x, pos.y - self.rect.y
    if x < 110 and y < 40:
      if self.confirming:
        self.confirming, self.message = False, ''
      else:
        self.dismiss()
      return
    try:
      view = self.controller.view()
    except SettingsError as exc:
      self.message, self.draft, self.confirming = str(exc), None, False
      return
    row = view['rows'][self.selected]
    if self.confirming:
      if 404 <= x <= 516 and 197 <= y <= 234:
        try:
          self.controller.save(*self.draft, acknowledged=True)
          self.message = '저장 확인 · 현재 상태는 별도 확인해'
        except SettingsError as exc:
          self.message = str(exc)
        self.confirming, self.draft = False, None
      return
    if 44 <= y <= 77:
      for i in range(3):
        if 16 + i * 172 <= x <= 176 + i * 172:
          self.selected, self.draft, self.message = i, None, ''
      return
    if 166 <= y <= 198:
      if row['editable'] and 20 <= x <= 392:
        i = 0 if x <= 200 else 1 if x >= 212 else None
        if i is not None:
          self.draft = (row['id'], bool(i), view['revision'])
          self.message = ''
      elif 404 <= x <= 516 and self.draft:
        self.confirming = True


class KoreanSettingsButton(Widget):
  def __init__(self, controller=None):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 402, 180))
    self.set_click_callback(lambda: gui_app.push_widget(KoreanSettingsPage(controller)))

  def _render(self, _):
    drawing.begin_frame()
    panel(0, 0, 402, 180, drawing.Color(24, 43, 40, 255))
    label('주행 설정', 28, 28, 36)
    label('크루즈 · ACC/E2E · MADS', 28, 89, 21, GREEN)
    label('저장한 값과 현재 상태 확인', 28, 134, 18, DIM)
    drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))


class DrivingSettingsRoot(SettingsLayoutSP):
  def __init__(self):
    super().__init__()
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.driving_status import enabled
    if enabled():
      from openpilot.selfdrive.ui.sunnypilot.mici.korean.native_driving import DrivingStatusButton
      self._scroller.add_widget(DrivingStatusButton())
      self._scroller._items.insert(0, self._scroller._items.pop())


class PhoneSettingsRoot(DrivingSettingsRoot):
  def __init__(self):
    super().__init__()
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_runtime import PhoneRuntime
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.native_phone import KoreanPhoneButton
    self.phone_runtime = PhoneRuntime(ui_state.params,
      allow_model_change=os.getenv('KOREAN_PHONE_MODEL_CHANGE', '0') == '1',
      allow_settings_change=os.getenv('KOREAN_PHONE_SETTINGS_WRITE', '0') == '1')
    self._update_phone()
    gui_app.add_nav_stack_tick(self._update_phone)
    atexit.register(self.close_phone)
    # No listener without explicit deployment configuration. The legacy PC
    # preview keeps its own loopback server and synthetic settings unchanged.
    if os.getenv('KOREAN_PHONE_CERT'):
      try:
        from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_transport import PhoneTransport
        self.phone_runtime.attach(PhoneTransport(self.phone_runtime.service,
          host=os.environ['KOREAN_PHONE_BIND'], port=int(os.environ['KOREAN_PHONE_PORT']),
          authority=os.environ['KOREAN_PHONE_AUTHORITY'], certfile=os.environ['KOREAN_PHONE_CERT'],
          keyfile=os.environ['KOREAN_PHONE_KEY']))
      except (OSError, ValueError, KeyError):
        self.phone_runtime.network_error = '폰 연결 설정을 확인해 줘'
    elif os.getenv('KOREAN_PHONE_LOCAL', '0') == '1':
      try:
        from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_transport import local_phone_transport
        self.phone_runtime.attach(local_phone_transport(self.phone_runtime.service,
          port=int(os.getenv('KOREAN_PHONE_PORT', '7443'))))
      except (OSError, ValueError):
        self.phone_runtime.network_error = 'Wi-Fi 주소나 폰 연결 인증서를 확인해 줘'
    if self.phone_runtime.road_input_available:
      try:
        from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.runtime import enabled as road_input_enabled
        if road_input_enabled():
          self.phone_runtime.attach_road_publisher()
      except (ImportError, OSError, RuntimeError):
        self.phone_runtime.network_error = '도로 입력 전달 서비스를 확인해 줘'
    self._scroller.add_widget(KoreanPhoneButton(self.phone_runtime))
    self._scroller._items.insert(0, self._scroller._items.pop())

  def _update_phone(self):
    self.phone_runtime.update(ui_state.sm, ui_state.started_frame, ui_state.is_release or ui_state.is_sp_release)

  def close_phone(self):
    gui_app.remove_nav_stack_tick(self._update_phone)
    self.phone_runtime.close()


class KoreanSettingsRoot(PhoneSettingsRoot):
  def __init__(self):
    super().__init__()
    self._scroller.add_widget(KoreanSettingsButton(self.phone_runtime.controller))
    self._scroller._items.insert(0, self._scroller._items.pop())
