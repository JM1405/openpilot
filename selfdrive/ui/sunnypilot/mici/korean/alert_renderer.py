"""Original MICI warning colors/gradient with fitted Korean text for 476x240.

Translations are exact string matches, never inferred from an event name.
Unmapped messages retain the original text. Raw strings stay in the payload.
"""
from functools import lru_cache
from pathlib import Path

from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing as rl
from openpilot.selfdrive.ui.sunnypilot.mici.korean.alerts import COLORS

FONT = Path(__file__).with_name('fonts') / 'AlertSans.ttf'
TRANSLATIONS = {
  'Pay Attention': '전방을 주시하세요',
  'Driver Distracted': '운전자 주의 분산',
  'Touch Steering Wheel': '핸들을 잡으세요',
  'Touch Steering Wheel: No Face Detected': '핸들을 잡으세요: 얼굴이 감지되지 않아요',
  'Driver Unresponsive': '운전자 응답 없음',
  'DISENGAGE IMMEDIATELY': '즉시 주행 보조를 해제하세요',
  'TAKE CONTROL IMMEDIATELY': '즉시 수동 조작하세요',
  'TAKE CONTROL': '수동으로 조작하세요',
  'Resume Driving Manually': '직접 운전을 재개하세요',
  'BRAKE!': '브레이크를 밟으세요!',
  'Risk of Collision': '충돌 위험',
  'Steering Assist Temporarily Unavailable': '조향 보조를 일시적으로 사용할 수 없어요',
  'System Unresponsive': '시스템 응답 없음',
  'Reboot Device': '장치를 다시 시작하세요',
}


@lru_cache(maxsize=96)
def font(size):
  from PIL import ImageFont
  return ImageFont.truetype(str(FONT), size)


def wrap(value, size, width=440):
  """Wrap complete text, including unspaced Hangul/long tokens."""
  lines = []
  for paragraph in value.split('\n'):
    line = ''
    for char in paragraph:
      if line and font(size).getlength(line + char) > width:
        # Prefer a word boundary when it avoids a very short line.
        split = line.rfind(' ')
        if split >= len(line) // 2:
          lines.append(line[:split])
          line = line[split + 1:] + char
        else:
          lines.append(line)
          line = char
      else:
        line += char
    lines.append(line.strip())
  return lines if value else []


@lru_cache(maxsize=128)
def text_layout(text1, text2, size):
  title = TRANSLATIONS.get(text1, text1)
  body = TRANSLATIONS.get(text2, text2)
  # AlertSize survives unchanged. Korean size fitting is a PC adaptation of
  # MICI's length-based typography, not a change to severity or event timing.
  maximum = {'small': 46, 'mid': 50, 'full': 54}[size]
  for point in range(maximum, 5, -1):
    secondary = max(6, round(point * .55))
    first, second = wrap(title, point), wrap(body, secondary)
    height = len(first) * point * 1.24 + len(second) * secondary * 1.35 + (10 if second else 0)
    if height <= 204:
      break
  y, result = 12.0, []
  for lines, pixels in ((first, point), (second, secondary)):
    for line in lines:
      ascent = font(pixels).getmetrics()[0]
      top = font(pixels).getbbox(line, anchor='ls')[1]
      # Store an alphabetic baseline for Canvas and an explicit native offset.
      result.append((line, 18, y - top, pixels, ascent))
      y += pixels * 1.24
    y += 10
  return result


def render_alert(presentation):
  if not presentation:
    return
  alert, alpha = presentation['alert'], presentation['alpha']
  rgb = COLORS[alert['alertStatus']]
  color = rl.Color(*rgb, int(255 * .9 * alpha))
  name = alert['alertType'].split('/')[0]
  height = 140 if name in ('preLaneChangeLeft', 'preLaneChangeRight', 'laneChange') else 200 if name == 'laneChangeBlocked' else 240
  solid = round(height * .2)
  rl.draw_rectangle(0, 0, 476, solid, color)
  rl.draw_rectangle_gradient_v(0, solid, 476, height - solid, color, rl.Color(*rgb, 0))
  for value, x, baseline, size, ascent in text_layout(alert['alertText1'], alert['alertText2'], alert['alertSize']):
    rl.alert_text(value, x, baseline, size, rl.Color(255, 255, 255, int(255 * .9 * alpha)), ascent)
