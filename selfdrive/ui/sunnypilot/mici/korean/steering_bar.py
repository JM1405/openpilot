"""MICI steering-utilization arc; pure display geometry, never a steering command."""
import colorsys
import math
import numpy as np

from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing
from openpilot.selfdrive.ui.sunnypilot.mici.korean.steering_arc_geometry import arc_bar_pts

RECT = (0, 0, 476, 240)


def attach_steering_bar(timeline):
  """Precompute the fade so random seeking cannot change recorded display state.

    D56 already stores the fresh, sign-reversed, filtered actual torque output.
    Its legacy source is explicit; do not fall back to the old command-based HUD value.
  """
  alpha = 0.0
  dt = 1 / timeline['metadata']['hz']
  for frame in timeline['frames']:
    style = frame['evidence'].get('road_style', {})
    valid = bool(style.get('torque_source') and style.get('status') != 'unknown' and not frame['display']['stale'])
    target = valid and style.get('status') not in ('disengaged', 'long_only')
    alpha = alpha + dt / (0.1 + dt) * (int(target) - alpha) if valid else 0.0
    frame['steering_bar'] = ({'torque': style['torque'], 'status': style['status'], 'alpha': alpha,
                              'source': style['torque_source']} if valid else None)
  timeline['metadata'].update(steering_style='mici_arc', implementation='D57')
  return timeline


def synthetic_bar(state):
  if state.stale or not state.lateral_active:
    return None
  return {'torque': state.steering_usage, 'alpha': 1.0,
          'status': 'engaged' if state.longitudinal_active else 'lat_only', 'source': 'synthetic'}


def hsv_blend(a, b, factor):
  if factor <= 0:
    return drawing.Color(*a, 255)
  if factor >= 1:
    return drawing.Color(*b, 255)
  h0, s0, v0 = colorsys.rgb_to_hsv(*(x / 255 for x in a))
  h1, s1, v1 = colorsys.rgb_to_hsv(*(x / 255 for x in b))
  dh = ((h1 - h0 + 0.5) % 1) - 0.5
  rgb = colorsys.hsv_to_rgb((h0 + factor * dh) % 1, s0 + factor * (s1 - s0), v0 + factor * (v1 - v0))
  return drawing.Color(*(int(c * 255) for c in rgb), 255)


def render_steering_bar(bar):
  if not bar or not all(math.isfinite(bar[k]) for k in ('torque', 'alpha')):
    return
  alpha = float(np.clip(bar['alpha'], 0, 1))
  if alpha < 0.001:
    return
  torque = float(np.clip(bar['torque'], -1, 1))
  magnitude = abs(torque)
  offset = float(np.interp(magnitude, [0.5, 1], [22, 26]))
  height = float(np.interp(magnitude, [0.5, 1], [14, 56]))
  radius = 1200 + height / 2
  cx, cy = 246, 240 + 1200 - offset
  span = alpha * 12.7
  background = arc_bar_pts(radius, height, -90 - span / 2, -90 + span / 2) + [cx, cy]
  foreground = arc_bar_pts(radius, height, -90, -90 + span / 2 * torque) + [cx, cy]
  active = bar['status'] in ('engaged', 'lat_only')
  opacity = float(np.interp(magnitude, [0.5, 1], [0.25, 0.5])) if active else 0.15
  bg = drawing.Color(255, 255, 255, int(255 * opacity * alpha))
  drawing.draw_ribbon_gradient(background.tolist(), [bg, bg], (0, 0), (1, 0))
  factor = max(0, magnitude - 0.75) * 4
  start = hsv_blend((255, 255, 255), (255, 200, 0), factor)
  end = hsv_blend((255, 255, 255), (255, 115, 0), factor)
  if not active:
    start = end = drawing.Color(255, 255, 255, int(255 * 0.35 * alpha))
  edge = min(background[:, 0]) if torque < 0 else max(background[:, 0])
  gradient_end = float(cx * 0.35 + edge * 0.65)
  # Match the original shader's horizontal start/end convention: t=0 at end.
  drawing.draw_ribbon_gradient(foreground.tolist(), [start, end], (cx, 0), (gradient_end, 0))
  if magnitude < 0.5:
    drawing.draw_circle_v(drawing.Vector2(cx, int(240 - offset - height / 2)), 5,
                           drawing.Color(182, 182, 182, int(255 * 0.9 * alpha)))
