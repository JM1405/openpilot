"""Render separately sourced 2D image detections; never infer policy awareness."""
import math

from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing

VEHICLE_COLOR = drawing.Color(65, 213, 241, 220)


def screen_boxes(detections, camera, lead=None):
  if not detections or not camera or detections['file_index'] != camera['file_index']:
    return []
  width, height = detections['image_size']
  if width <= 0 or height <= 0:
    return []
  ox, oy, w, h = camera['rect']
  boxes = []
  for item in detections['boxes']:
    coords = item['xyxy']
    if item.get('class_id') not in (2, 3, 5, 7) or not 0.3 <= item.get('confidence', 0) <= 1:
      continue
    if len(coords) != 4 or not all(math.isfinite(x) for x in coords):
      continue
    x1, y1, x2, y2 = coords
    if not 0 <= x1 < x2 <= width or not 0 <= y1 < y2 <= height:
      continue
    left, top = max(0, ox + x1 / width * w), max(0, oy + y1 / height * h)
    right, bottom = min(476, ox + x2 / width * w), min(240, oy + y2 / height * h)
    if right - left < 2 or bottom - top < 2:
      continue
    if lead:
      lx1, lx2 = (lead.x - lead.width / 2) * 476, (lead.x + lead.width / 2) * 476
      ly1, ly2 = (lead.y - lead.height / 2) * 240, (lead.y + lead.height / 2) * 240
      overlap = max(0, min(right, lx2) - max(left, lx1)) * max(0, min(bottom, ly2) - max(top, ly1))
      union = (right - left) * (bottom - top) + (lx2 - lx1) * (ly2 - ly1) - overlap
      if union > 0 and overlap / union > 0.35:
        continue  # visual overlap suppression only, NOT association of two object identities
    boxes.append([left, top, right, bottom])
  return boxes


def render_vehicles(detections, camera, lead=None):
  boxes = screen_boxes(detections, camera, lead)
  if boxes:
    drawing.begin_scissor_mode(0, 0, 476, 240)
    for left, top, right, bottom in boxes:
      for a, b in (((left, top), (right, top)), ((right, top), (right, bottom)),
                   ((right, bottom), (left, bottom)), ((left, bottom), (left, top))):
        drawing.draw_line_ex(a, b, 0.9, VEHICLE_COLOR)
    drawing.end_scissor_mode()
  return len(boxes)
