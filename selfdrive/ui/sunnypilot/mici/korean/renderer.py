"""Native raylib C4 display, sharing sunnypilot's fonts and drawing runtime."""
import math
from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing as rl

from openpilot.selfdrive.ui.sunnypilot.mici.korean.alert_renderer import render_alert
from openpilot.selfdrive.ui.sunnypilot.mici.korean.state import Display, EventKind
from openpilot.selfdrive.ui.sunnypilot.mici.korean.steering_bar import render_steering_bar

WIDTH, HEIGHT, ROAD_WIDTH = 536, 240, 476
WHITE = rl.Color(245, 248, 250, 255)
GREEN = rl.Color(29, 235, 131, 255)
DIM = rl.Color(100, 113, 121, 255)
RED = rl.Color(255, 62, 73, 255)
AMBER = rl.Color(255, 194, 72, 255)


def line(x1, y1, x2, y2, color=WHITE, width=2.5):
  rl.draw_line_ex(rl.Vector2(x1, y1), rl.Vector2(x2, y2), width, color)


def text(value, x, y, size=20, color=WHITE):
  rl.centered_text(value, x, y, size, color)


def wheel(x, y, color, radius=17):
  rl.draw_ring(rl.Vector2(x, y), radius - 2.5, radius, 0, 360, 48, color)
  line(x - radius + 3, y - 2, x + radius - 3, y - 2, color)
  line(x, y, x, y + radius - 2, color, 3)
  rl.draw_circle_v(rl.Vector2(x, y), 4, color)


def cruise(x, y, color):
  rl.draw_ring(rl.Vector2(x, y), 15, 17.5, 140, 400, 40, color)
  for degree in (150, 205, 260, 315, 370):
    a = math.radians(degree)
    line(x + 13 * math.cos(a), y + 13 * math.sin(a), x + 17 * math.cos(a), y + 17 * math.sin(a), color, 2)
  line(x, y, x + 8, y - 9, color, 3)
  rl.draw_circle_v(rl.Vector2(x, y), 3, color)


def navigation(x, y, state):
  color = WHITE if state == 'active' else AMBER if state == 'lost' else DIM
  rl.draw_ring(rl.Vector2(x, y - 5), 9, 11.5, 0, 360, 30, color)
  line(x - 9, y + 2, x, y + 17, color, 2.5)
  line(x, y + 17, x + 9, y + 2, color, 2.5)
  if state == 'active':
    line(x - 4, y - 5, x - 1, y - 2, color, 2)
    line(x - 1, y - 2, x + 5, y - 8, color, 2)
  elif state == 'lost':
    line(x - 14, y - 17, x + 13, y + 13, color, 2.5)
  else:
    rl.draw_circle_v(rl.Vector2(x, y - 5), 2, color)


def event_icon(kind, x, y, color=AMBER):
  if kind in (EventKind.CAMERA, EventKind.SECTION):
    rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(x - 17, y - 11, 34, 24), 0.2, 6, 2.5, color)
    rl.draw_ring(rl.Vector2(x, y + 1), 5, 7, 0, 360, 24, color)
    line(x - 10, y - 15, x + 6, y - 15, color, 3)
    if kind == EventKind.SECTION:
      line(x - 22, y + 19, x + 22, y + 19, color, 2)
  elif kind == EventKind.BUMP:
    line(x - 22, y + 11, x - 13, y + 11, color)
    points = [rl.Vector2(x - 13 + i * 26 / 16, y + 11 - 19 * math.sin(math.pi * i / 16)) for i in range(17)]
    for a, b in zip(points, points[1:], strict=False):
      rl.draw_line_ex(a, b, 3, color)
    line(x + 13, y + 11, x + 22, y + 11, color)
  elif kind == EventKind.CURVE_LEFT:
    # Two road edges rather than a turn arrow.
    for offset in (-6, 6):
      points = [(x + 10 + offset, y + 19), (x + 10 + offset, y + 6),
                (x + 5 + offset, y - 5), (x - 8 + offset, y - 14), (x - 18 + offset, y - 16)]
      for a, b in zip(points, points[1:], strict=False):
        line(*a, *b, color, 3)
  else:
    line(x - 8, y + 18, x - 8, y - 7, color, 3)
    if kind == EventKind.EXIT_RIGHT:
      line(x - 8, y - 7, x - 8, y - 20, color, 3)
      line(x - 8, y + 3, x + 15, y - 14, color, 3)
      line(x + 15, y - 14, x + 3, y - 13, color, 3)
      line(x + 15, y - 14, x + 12, y - 2, color, 3)
    else:
      line(x - 8, y - 7, x + 18, y - 7, color, 3)
      line(x + 18, y - 7, x + 8, y - 17, color, 3)
      line(x + 18, y - 7, x + 8, y + 3, color, 3)


class KoreanHudRenderer:
  def render(self, state: Display, *, steering_bar=None, alert_presentation=None, suppress_road=False, wheel_critical=None):
    # Road/background belongs to the camera or the PC fixture, not this HUD.
    rl.begin_scissor_mode(0, 0, ROAD_WIDTH, HEIGHT)
    if alert_presentation is None and not suppress_road:
      if state.lead is not None:
        lead = state.lead
        x, y = lead.x * ROAD_WIDTH, lead.y * HEIGHT
        w, h = lead.width * ROAD_WIDTH, lead.height * HEIGHT
        color = RED if state.lead_emphasis else WHITE
        length = min(12, w * 0.22, h * 0.22)
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
          px, py = x + dx * w / 2, y + dy * h / 2
          for tint, weight in ((rl.Color(10, 15, 20, 210), 5), (color, 2.5)):
            line(px, py, px - dx * length, py, tint, weight)
            line(px, py, px, py - dy * length, tint, weight)

      # Driver monitoring indicator remains independent of lead attention.
      dm = DIM if state.driver_attentive is None else WHITE if state.driver_attentive else AMBER
      rl.draw_circle_v(rl.Vector2(27, 24), 8, dm)
      rl.draw_ellipse(27, 43, 14, 7, dm)
      rl.draw_ring(rl.Vector2(27, 30), 23, 25, 145, 215, 18,
                   DIM if state.driver_attentive is None else GREEN if state.driver_attentive else AMBER)

      if state.limit is not None:
        rl.draw_circle_v(rl.Vector2(443, 30), 24, RED)
        rl.draw_circle_v(rl.Vector2(443, 30), 19, WHITE)
        text(round(state.limit), 443, 16, 21, rl.BLACK)

      render_steering_bar(steering_bar)

      if state.event is not None:
        event = state.event
        panel_width = 158 if event.kind == EventKind.SECTION else 86
        rl.draw_rectangle_rounded(rl.Rectangle(12, 131, panel_width, 80), 0.18, 8, rl.Color(8, 15, 23, 230))
        event_icon(event.kind, 55, 153)
        distance = f'{event.distance / 1000:.1f} km' if event.distance >= 1000 else f'{round(event.distance)} m'
        text(distance, 55, 182, 17)
        if event.kind == EventKind.SECTION:
          text('AVG', 130, 143, 11, DIM)
          text(round(event.average_speed), 130, 164, 24)

      if state.stale:
        text('—', ROAD_WIDTH / 2, 170, 32, AMBER)
    render_alert(alert_presentation)
    rl.end_scissor_mode()

    rl.draw_rectangle(ROAD_WIDTH, 0, WIDTH - ROAD_WIDTH, HEIGHT, rl.BLACK)
    required = (state.alert is not None and state.alert.alertStatus == 'critical' and state.alert.alertHudVisual == 'steerRequired')
    required = required if wheel_critical is None else wheel_critical
    wheel(506, 29, RED if required else GREEN if state.lateral_active else DIM)
    cruise(506, 90, GREEN if state.longitudinal_active else DIM)
    text(round(state.set_speed) if state.set_speed is not None else '—', 506, 114, 25,
         WHITE if state.longitudinal_active else DIM)
    navigation(506, 173, state.navigation_state)
    text(state.mode, 506, 208, 17, WHITE if not state.stale else DIM)
