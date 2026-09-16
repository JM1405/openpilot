"""Korean typography over the original on-device alert owner and animation."""
import pyray as rl
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.selfdrive.ui.mici.onroad.alert_renderer import AlertRenderer
from openpilot.selfdrive.ui.sunnypilot.mici.korean.alert_renderer import TRANSLATIONS
from openpilot.selfdrive.ui.sunnypilot.mici.korean.drawing import native_alert_font


class KoreanAlertRenderer(AlertRenderer):
  # get_alert/will_render/_render remain upstream: startup/watchdog, special
  # icons, alert lifetime, brightness and animations are not PC simulations.
  def _draw_text(self, alert, alert_layout):
    if alert_layout.icon is not None or not any(t in TRANSLATIONS for t in (alert.text1, alert.text2)):
      return super()._draw_text(alert, alert_layout)
    title, body = (TRANSLATIONS.get(t, t) for t in (alert.text1, alert.text2))
    font = native_alert_font(title + body)
    width = max(1, alert_layout.text_rect.width - 18)

    def wrap(value, pixels):
      lines, line = [], ''
      for char in value:
        if char == '\n' or (line and measure_text_cached(font, line + char, pixels).x > width):
          lines.append(line)
          line = ''
        if char != '\n':
          line += char
      if line:
        lines.append(line)
      return lines

    for size in range(54, 9, -1):
      small = max(10, round(size * .55))
      first, second = wrap(title, size), wrap(body, small)
      if len(first) * size * 1.24 + len(second) * small * 1.24 + 10 <= self._rect.height - 24:
        break
    x, y = alert_layout.text_rect.x, alert_layout.text_rect.y + 5
    for lines, pixels, opacity in ((first, size, .9), (second, small, .9)):
      for line in lines:
        rl.draw_text_ex(font, line, rl.Vector2(x, y), pixels, 0, rl.Color(255, 255, 255, int(255 * opacity * self._alpha_filter.x)))
        y += pixels * 1.24
      y += 10
