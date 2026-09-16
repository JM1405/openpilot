"""Offline port of the pinned MICI road design, with explicit archive freshness.

Rules/colors: selfdrive/ui/mici/onroad/model_renderer.py at b67898fac4e9.
The shared calibrated/clipped PC camera projection is retained. Optional rainbow
and experimental acceleration coloring are not enabled by this normal-style port.
"""
import colorsys
import numpy as np

from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing
from openpilot.selfdrive.ui.sunnypilot.mici.korean.messages import Sample, number
from openpilot.selfdrive.ui.sunnypilot.mici.korean.road import project_ribbon, VIEWPORT
from openpilot.selfdrive.ui.sunnypilot.mici.korean.state import fresh

STYLE_SERVICES = frozenset(('selfdriveState', 'selfdriveStateSP', 'onroadEvents', 'controlsState',
                            'carParams', 'carOutput', 'carControl', 'longitudinalPlan'))
THROTTLE = [(13, 248, 122, 102), (114, 255, 92, 89), (114, 255, 92, 0)]
NO_THROTTLE = [(242, 242, 242, 102), (242, 242, 242, 89), (242, 242, 242, 0)]


class RoadStyleAdapter:
  def __init__(self, *, legacy=False, hz=20):
    self.samples = {}
    self.legacy = legacy
    self.dt = 1 / hz
    self.torque = 0.0
    self.blend = 1.0

  def consume(self, event):
    name = event.which()
    if name in STYLE_SERVICES:
      value = getattr(event, name)
      data = [e.to_dict() for e in value] if name == 'onroadEvents' else value.to_dict()
      sample = Sample(event.logMonoTime / 1e9, bool(event.valid), data)
      if name not in self.samples or sample.timestamp >= self.samples[name].timestamp:
        self.samples[name] = sample

  def get(self, name, now):
    s = self.samples.get(name)
    return s.data if s and s.valid and s.timestamp <= now and (name == 'carParams' or fresh(s.timestamp, now, 0.5)) else None

  def at(self, now):
    ss = self.get('selfdriveState', now)
    source = 'selfdriveState'
    if self.legacy and 'selfdriveState' not in self.samples:
      control = self.get('controlsState', now)
      ss = control.get('deprecated') if control else None
      source = 'controlsState.deprecated'
    status = 'unknown'
    if ss:
      state = ss.get('state')
      mads = (self.get('selfdriveStateSP', now) or {}).get('mads', {})
      if state == 'preEnabled' or mads.get('state') in ('paused', 'overriding'):
        status = 'override'
      elif state == 'overriding' and (not mads.get('available') or
                                     any(e.get('overrideLongitudinal') for e in (self.get('onroadEvents', now) or [])) or
                                     self.get('onroadEvents', now) is None):
        status = 'override'
      elif mads.get('available'):
        status = ('engaged' if ss.get('enabled') else 'lat_only') if mads.get('enabled') else (
          'long_only' if ss.get('enabled') else 'disengaged')
      else:
        status = 'engaged' if ss.get('enabled') else 'disengaged'
    output = self.get('carOutput', now)
    torque_source = 'carOutput.actuatorsOutput.torque'
    if self.legacy and 'carOutput' not in self.samples:
      control = self.get('carControl', now)
      output = control.get('deprecated') if control else None
      torque_source = 'carControl.deprecated.actuatorsOutput.torque'
    torque = number((output or {}).get('actuatorsOutput', {}).get('torque'))
    if torque is None:
      self.torque = 0.0
    else:
      self.torque += self.dt / (0.1 + self.dt) * (-torque - self.torque)
    cp = self.get('carParams', now)
    plan = self.get('longitudinalPlan', now)
    allow = True if cp and cp.get('openpilotLongitudinalControl') is False else (
      plan.get('allowThrottle') if cp and plan and not self.legacy else None)
    if allow is None:
      self.blend = 0.0  # Archive has no evidence yet: neutral, never assume stock longitudinal.
    elif status not in ('disengaged', 'unknown'):
      self.blend += self.dt / (0.25 + self.dt) * (int(allow) - self.blend)
    blend = round(self.blend * 100) / 100
    colors = [[int((1 - blend) * a + blend * b) for a, b in zip(c, d, strict=True)]
              for c, d in zip(NO_THROTTLE, THROTTLE, strict=True)]
    return {'status': status, 'visible': status not in ('unknown', 'disengaged'), 'state_source': source,
            'state_timestamp': self.samples[source.split('.')[0]].timestamp if source.split('.')[0] in self.samples else None,
            'torque': self.torque, 'torque_source': torque_source if torque is not None else None,
            'allow_throttle': allow, 'path_colors': colors, 'path_stops': [0, 0.5, 1],
            'style': 'mici_normal', 'experimental_recorded': bool(ss and ss.get('experimentalMode'))}


def sample_cut(line, distance):
  xs = line.get('x', [])
  if not xs:
    return {}
  count = max((i + 1 for i, x in enumerate(xs) if x <= distance), default=1)
  return {k: line.get(k, [])[:count] for k in ('x', 'y', 'z')}


def project_mici_road(matrix, model, height, lead_distance=None):
  position = model.get('position', {})
  xs = position.get('x', [])
  max_distance = float(np.clip(xs[-1], 10, 100)) if xs and np.isfinite(xs).all() else 100.0
  path_distance = max_distance
  if lead_distance is not None and np.isfinite(lead_distance) and lead_distance > 0:
    doubled = lead_distance * 2
    path_distance = float(np.clip(doubled - min(doubled * 0.35, 10), 0, max_distance))
  path = project_ribbon(matrix, sample_cut(position, path_distance), 0.9, height, path_distance)
  probabilities = model.get('laneLineProbs', [])
  lanes, edges = [], []
  for i, (line, prob) in enumerate(zip(model.get('laneLines', [])[:4], probabilities[:4], strict=False)):
    if not np.isfinite(prob) or not 0 < prob <= 1:
      continue
    # The pinned source keeps 0.16 for index 3 after changing it at index 1.
    width = (0.12 if i == 0 else 0.16) * prob
    sections = project_ribbon(matrix, sample_cut(line, max_distance), width, max_distance=max_distance)
    if sections:
      lanes.append({'index': i, 'probability': prob, 'half_width': width, 'sections': sections})
  for i, (line, std) in enumerate(zip(model.get('roadEdges', [])[:2], model.get('roadEdgeStds', [])[:2], strict=False)):
    if not np.isfinite(std) or std < 0:
      continue
    confidence = float(np.clip(1 - std, 0, 1))
    sections = project_ribbon(matrix, sample_cut(line, max_distance), 0.16, max_distance=max_distance)
    if confidence > 0 and sections:
      adjacent_prob = probabilities[i + 1] if len(probabilities) > i + 1 else None
      adjacent = bool(adjacent_prob is not None and np.isfinite(adjacent_prob) and adjacent_prob < 0.25)
      edges.append({'index': i, 'probability': confidence, 'adjacent': adjacent, 'half_width': 0.16, 'sections': sections})
  return {'profile': 'mici', 'path': path, 'lanes': lanes, 'edges': edges, 'path_max_distance': path_distance}


def line_color(probability, adjacent, left, style):
  rgb = (0, 255, 64) if adjacent and style['status'] in ('engaged', 'lat_only', 'long_only') else (255, 255, 255)
  alpha = int(np.clip(probability, 0, 0.7) * 255)
  torque = style['torque']
  if adjacent and abs(torque) > 0.6 and left == (torque > 0):
    f = float(np.interp(abs(torque), [0.6, 0.8], [0, 1]))
    h0, s0, v0 = colorsys.rgb_to_hsv(*(x / 255 for x in rgb))
    h1, s1, v1 = colorsys.rgb_to_hsv(1, 115 / 255, 0)
    dh = ((h1 - h0 + 0.5) % 1) - 0.5
    rgb = tuple(int(x * 255) for x in colorsys.hsv_to_rgb((h0 + f * dh) % 1, s0 + f * (s1 - s0), v0 + f * (v1 - v0)))
    alpha = 255  # pinned blend_colors uses raylib.color_from_hsv, which returns opaque alpha
  return drawing.Color(*rgb, alpha)


def render_mici_road(road):
  style = road.get('style', {})
  if not style.get('visible'):
    return
  drawing.begin_scissor_mode(0, 0, *VIEWPORT)
  for lane in road['lanes']:
    c = line_color(lane['probability'], lane['index'] in (1, 2), lane['index'] in (0, 1), style)
    drawing.draw_polygons_gradient([s['points'] for s in lane['sections']], [c, c], [0, 1])
  for edge in road['edges']:
    c = line_color(edge['probability'], edge['adjacent'], edge['index'] == 0, style)
    drawing.draw_polygons_gradient([s['points'] for s in edge['sections']], [c, c], [0, 1])
  drawing.draw_polygons_gradient([s['points'] for s in road['path']], style['path_colors'], style['path_stops'])
  drawing.end_scissor_mode()
