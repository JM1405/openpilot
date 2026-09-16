"""Project recorded model paths and perceived lane lines onto the matched image.

model.position needs camera height added; laneLines already carry road-surface z,
as in the pinned MICI ModelRenderer. This is model visualization, not a new plan.
"""
import numpy as np

from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing

VIEWPORT = (476, 240)
MIN_LANE_PROB = 0.1  # PC display choice, not a perception/control threshold


def clip_polygon(points, axis, bound, greater):
  """Clip a convex polygon in 3D or 2D without joining disjoint curve sections."""
  output = []
  for a, b in zip(points, points[1:] + points[:1], strict=True):
    inside_a = a[axis] >= bound if greater else a[axis] <= bound
    inside_b = b[axis] >= bound if greater else b[axis] <= bound
    if inside_a:
      output.append(a)
    if inside_a != inside_b:
      intersection = a + (b - a) * ((bound - a[axis]) / (b[axis] - a[axis]))
      intersection[axis] = bound  # prevent roundoff crossing the exact clipping boundary
      output.append(intersection)
  return output


def project_ribbon(matrix, line, half_width, z_offset=0.0, max_distance=100.0):
  axes = [line.get(k, []) for k in ('x', 'y', 'z')]
  if len(axes[0]) < 2 or any(len(a) != len(axes[0]) for a in axes):
    return []
  points = np.asarray(axes, dtype=float).T
  if not np.isfinite(points).all() or np.any(np.diff(points[:, 0]) <= 0):
    return []
  if not np.isfinite(matrix).all() or not np.isfinite([half_width, z_offset, max_distance]).all() or half_width <= 0:
    return []
  offset_left = np.array([0, -half_width, z_offset])
  offset_right = np.array([0, half_width, z_offset])
  sections = []
  for a, b in zip(points, points[1:], strict=False):
    poly = [a + offset_left, a + offset_right, b + offset_right, b + offset_left]
    poly = clip_polygon(poly, 0, 1.0, True)
    poly = clip_polygon(poly, 0, max_distance, False)
    if len(poly) < 3:
      continue
    distance = float(np.mean([p[0] for p in poly]))
    poly = [matrix @ p for p in poly]
    poly = clip_polygon(poly, 2, 0.1, True)
    poly = [p[:2] / p[2] for p in poly]
    for axis, bound, greater in ((0, 0, True), (0, VIEWPORT[0], False), (1, 0, True), (1, VIEWPORT[1], False)):
      poly = clip_polygon(poly, axis, bound, greater)
    if len(poly) >= 3:
      sections.append({'points': [p.tolist() for p in poly], 'distance': distance})
  return sections


def project_road(matrix, model, height):
  path = project_ribbon(matrix, model.get('position', {}), 0.9, height)
  lanes = []
  # Pair by original index; missing/invalid probabilities never imply a confident line.
  for index, (line, probability) in enumerate(zip(model.get('laneLines', []), model.get('laneLineProbs', []), strict=False)):
    if not np.isfinite(probability) or not MIN_LANE_PROB <= probability <= 1:
      continue
    sections = project_ribbon(matrix, line, 0.07)
    if sections:
      lanes.append({'index': index, 'probability': probability, 'sections': sections})
  return {'path': path, 'lanes': lanes}


def render_road(road, *, lateral_active):
  if not road:
    return
  drawing.begin_scissor_mode(0, 0, *VIEWPORT)

  def ribbon(sections, rgb, opacity):
    for section in sections:
      fade = float(np.clip((100 - section['distance']) / 75, 0, 1))
      color = drawing.Color(*rgb, round(opacity * fade))
      p = section['points']
      for i in range(1, len(p) - 1):
        # Raylib expects counterclockwise triangles; Canvas accepts either winding.
        a, b, c = p[0], p[i], p[i + 1]
        if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) > 0:
          b, c = c, b
        drawing.draw_triangle(a, b, c, color)

  ribbon(road['path'], (45, 224, 137) if lateral_active else (185, 199, 208), 88 if lateral_active else 50)
  for lane in road['lanes']:
    ribbon(lane['sections'], (245, 249, 255), 210 * lane['probability'])
  drawing.end_scissor_mode()
