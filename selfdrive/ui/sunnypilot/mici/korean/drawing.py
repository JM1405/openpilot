"""One display list for both native raylib and the browser preview.

The browser adapter changes only the drawing backend. State processing,
geometry, colors and scenario data all run in Python from this checkout.
"""
from typing import NamedTuple


class Color(NamedTuple):
  r: int
  g: int
  b: int
  a: int


class Vector2(NamedTuple):
  x: float
  y: float


class Rectangle(NamedTuple):
  x: float
  y: float
  width: float
  height: float


BLACK = Color(0, 0, 0, 255)
WHITE = Color(255, 255, 255, 255)
_commands: list = []


def begin_frame():
  _commands.clear()


def commands() -> list:
  return _commands.copy()


def draw_line_ex(start, end, width, color):
  _commands.append(('line', [start, end, width, color]))


def draw_circle_v(center, radius, color):
  _commands.append(('circle', [center, radius, color]))


def draw_ellipse(x, y, rx, ry, color):
  _commands.append(('ellipse', [x, y, rx, ry, color]))


def draw_ring(center, inner, outer, start, end, segments, color):
  _commands.append(('ring', [center, inner, outer, start, end, segments, color]))


def draw_rectangle(x, y, width, height, color):
  _commands.append(('rect', [x, y, width, height, color]))


def draw_rectangle_rounded(rect, roundness, segments, color):
  _commands.append(('rounded', [rect, roundness, segments, color]))


def draw_rectangle_rounded_lines_ex(rect, roundness, segments, width, color):
  _commands.append(('rounded_outline', [rect, roundness, segments, width, color]))


def draw_rectangle_gradient_v(x, y, width, height, top, bottom):
  _commands.append(('gradient', [x, y, width, height, top, bottom]))


def draw_triangle(a, b, c, color):
  _commands.append(('triangle', [a, b, c, color]))


def draw_polygons_gradient(polygons, colors, stops):
  if polygons:
    _commands.append(('polygons_gradient', [polygons, colors, stops]))


def draw_ribbon_gradient(points, colors, start, end):
  _commands.append(('ribbon_gradient', [points, colors, start, end]))


def centered_text(value, x, y, size, color):
  _commands.append(('text', [str(value), x, y, size, color]))


def alert_text(value, x, baseline, size, color, ascent):
  _commands.append(('alert_text', [value, x, baseline, size, color, ascent]))


def begin_scissor_mode(x, y, width, height):
  _commands.append(('clip', [x, y, width, height]))


def end_scissor_mode():
  _commands.append(('end_clip', []))


_native_alert_font = None
_native_alert_chars = set()


def translated_hud(items, offset):
  """Translate HUD primitives when the native Scroller moves the camera widget."""
  x, y = offset
  result = []
  for op, args in items:
    a = list(args)
    if op in ('line', 'triangle'):
      for i in range(2 if op == 'line' else 3):
        a[i] = (a[i][0] + x, a[i][1] + y)
    elif op in ('circle', 'ring'):
      a[0] = (a[0][0] + x, a[0][1] + y)
    elif op in ('rounded', 'rounded_outline'):
      a[0] = (a[0][0] + x, a[0][1] + y, *a[0][2:])
    elif op in ('ellipse', 'rect', 'gradient', 'clip'):
      a[0], a[1] = a[0] + x, a[1] + y
    elif op in ('text', 'alert_text'):
      a[1], a[2] = a[1] + x, a[2] + y
    elif op != 'end_clip':
      raise ValueError(f'Not a HUD primitive: {op}')
    result.append((op, a))
  return result


def native_alert_font(value):
  global _native_alert_font, _native_alert_chars
  import pyray as native
  from openpilot.selfdrive.ui.sunnypilot.mici.korean.alert_renderer import FONT
  chars = set(value)
  if _native_alert_font is None or not chars <= _native_alert_chars:
    _native_alert_chars.update(chars or {' '})
    codepoints = sorted(map(ord, _native_alert_chars))
    if _native_alert_font is not None:
      native.unload_font(_native_alert_font)
    buffer = native.ffi.new('int[]', codepoints)
    _native_alert_font = native.load_font_ex(str(FONT), 64, native.ffi.cast('int *', buffer), len(codepoints))
    native.set_texture_filter(_native_alert_font.texture, native.TextureFilter.TEXTURE_FILTER_BILINEAR)
  return _native_alert_font


def render_native(items, *, offset=(0, 0)):
  if offset != (0, 0):
    items = translated_hud(items, offset)
  import pyray as native
  from openpilot.system.ui.lib.application import gui_app, FontWeight
  from openpilot.system.ui.lib.text_measure import measure_text_cached

  for op, a in items:
    if op == 'line':
      native.draw_line_ex(native.Vector2(*a[0]), native.Vector2(*a[1]), a[2], native.Color(*a[3]))
    elif op == 'circle':
      native.draw_circle_v(native.Vector2(*a[0]), a[1], native.Color(*a[2]))
    elif op == 'ellipse':
      native.draw_ellipse(round(a[0]), round(a[1]), *a[2:4], native.Color(*a[4]))
    elif op == 'ring':
      native.draw_ring(native.Vector2(*a[0]), *a[1:6], native.Color(*a[6]))
    elif op == 'rect':
      native.draw_rectangle(*(round(v) for v in a[:4]), native.Color(*a[4]))
    elif op == 'rounded':
      native.draw_rectangle_rounded(native.Rectangle(*a[0]), *a[1:3], native.Color(*a[3]))
    elif op == 'rounded_outline':
      native.draw_rectangle_rounded_lines_ex(native.Rectangle(*a[0]), *a[1:4], native.Color(*a[4]))
    elif op == 'gradient':
      native.draw_rectangle_gradient_v(*(round(v) for v in a[:4]), native.Color(*a[4]), native.Color(*a[5]))
    elif op == 'triangle':
      native.draw_triangle(*(native.Vector2(*v) for v in a[:3]), native.Color(*a[3]))
    elif op == 'polygons_gradient':
      import numpy as np
      from openpilot.system.ui.lib.shader_polygon import draw_polygon, Gradient
      gradient = Gradient((0, 1), (0, 0), [native.Color(*c) for c in a[1]], a[2])
      for polygon in a[0]:
        for i in range(1, len(polygon) - 1):
          # Degenerate fourth vertex adapts each clipped convex fan triangle to
          # the upstream two-chain ribbon shader without dropping odd vertices.
          points = np.array([polygon[0], polygon[i], polygon[i + 1], polygon[i + 1]])
          draw_polygon(native.Rectangle(0, 0, 476, 240), points, gradient=gradient)
    elif op == 'ribbon_gradient':
      import numpy as np
      from openpilot.system.ui.lib.shader_polygon import draw_polygon, Gradient
      gradient = Gradient((a[2][0] / 476, a[2][1] / 240), (a[3][0] / 476, a[3][1] / 240),
                          [native.Color(*c) for c in a[1]], [0, 1])
      draw_polygon(native.Rectangle(0, 0, 476, 240), np.array(a[0]), gradient=gradient)
    elif op == 'text':
      font = gui_app.font(FontWeight.DISPLAY)
      size = measure_text_cached(font, a[0], a[3])
      native.draw_text_ex(font, a[0], native.Vector2(a[1] - size.x / 2, a[2]), a[3], 0, native.Color(*a[4]))
    elif op == 'alert_text':
      font = native_alert_font(a[0])
      native.draw_text_ex(font, a[0], native.Vector2(a[1], a[2] - a[5]), a[3], 0, native.Color(*a[4]))
    elif op == 'clip':
      native.begin_scissor_mode(*(round(v) for v in a))
    elif op == 'end_clip':
      native.end_scissor_mode()
    else:
      raise ValueError(f'Unknown drawing operation {op}')
