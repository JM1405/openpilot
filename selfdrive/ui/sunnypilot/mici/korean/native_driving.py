"""Read-only native driving status. Shares the presenter with the onroad view."""
import time
import pyray as rl

from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.mici.onroad.hud_renderer import HudRenderer, SET_SPEED_NA
from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing
from openpilot.selfdrive.ui.sunnypilot.mici.korean.driving_status import DrivingStatusMonitor, WAITING


def observe(monitor):
  return monitor.update(ui_state.sm, time.monotonic(), started=ui_state.started,
                        started_frame=ui_state.started_frame, started_time=ui_state.started_time, CP=ui_state.CP)


def text(value, x, y, size=17, color=(239, 245, 244, 255)):
  drawing.alert_text(value, x, y + size, size, drawing.Color(*color), size)


def page_commands(status, metric=True):
  drawing.begin_frame()
  drawing.draw_rectangle(0, 0, 536, 240, drawing.Color(8, 17, 19, 255))
  text('‹ 뒤로', 16, 10, 19)
  text('주행 보조 상태', 202, 10, 21)
  text(status.title, 20, 55, 26)
  text(status.detail or '주변 상황을 계속 확인해', 20, 96, 18)
  text(status.speed_label, 20, 143, 14, (161, 180, 174, 255))
  text(status.speed_text(metric), 20, 165, 29)
  text(status.steering_text, 278, 167, 19)
  text('버튼 요청 후 실제 상태를 확인해', 20, 216, 13, (161, 180, 174, 255))
  return drawing.commands()


def speed_commands(status, metric=True):
  drawing.begin_frame()
  if status.set_speed_kph is None:
    return []
  drawing.draw_rectangle_rounded(drawing.Rectangle(12, 14, 162, 92), .2, 6, drawing.Color(12, 18, 24, 225))
  previous = status.speed_label == '이전 설정속도'
  color = (197, 208, 212, 255) if previous else (239, 245, 244, 255)
  text('이전 설정' if previous else '설정속도', 24, 24, 16, color)
  text(status.speed_text(metric), 24, 53, 29, color)
  return drawing.commands()


class DrivingHudRenderer(HudRenderer):
  def __init__(self):
    super().__init__()
    self.driving_status = WAITING

  def _update_state(self):
    super()._update_state()
    speed = self.driving_status.set_speed_kph
    self.set_speed = speed if speed is not None else SET_SPEED_NA
    self.is_cruise_set = speed is not None

  def drawing_top_icons(self):
    return self.driving_status.set_speed_kph is not None and self._can_draw_top_icons

  def _draw_set_speed(self, rect):
    # Replace the transient MAX number in-place, so the set speed appears once.
    if self._can_draw_top_icons:
      drawing.render_native(speed_commands(self.driving_status, ui_state.is_metric), offset=(rect.x, rect.y))


class DrivingStatusPage(Widget):
  def __init__(self):
    super().__init__()
    self.monitor = DrivingStatusMonitor()
    self.set_rect(rl.Rectangle(0, 0, 536, 240))

  def _render(self, _):
    drawing.render_native(page_commands(observe(self.monitor), ui_state.is_metric), offset=(self.rect.x, self.rect.y))

  def _handle_mouse_release(self, pos):
    if 0 <= pos.x - self.rect.x < 110 and 0 <= pos.y - self.rect.y < 40:
      self.dismiss()


class DrivingStatusButton(Widget):
  def __init__(self):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 402, 180))
    self.set_click_callback(lambda: gui_app.push_widget(DrivingStatusPage()))

  def _render(self, _):
    drawing.begin_frame()
    drawing.draw_rectangle_rounded(drawing.Rectangle(0, 0, 402, 180), .15, 6, drawing.Color(24, 43, 40, 255))
    text('주행 보조 상태', 28, 28, 32)
    text('설정속도 / 대기 / 해제 / 재개', 28, 89, 20)
    text('현재 상태와 다음 조작 확인', 28, 134, 18)
    drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))
