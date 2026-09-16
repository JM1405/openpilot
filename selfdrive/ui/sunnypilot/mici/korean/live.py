"""Read-only SubMaster adapter for the actual MICI onroad renderer.

Uses receive time for liveness and logMonoTime for radar/model association.
No subscriptions, publishers, settings writes, synthetic navigation or detector.
"""
from dataclasses import replace
from math import isfinite
import numpy as np

from openpilot.selfdrive.ui.sunnypilot.mici.korean.messages import MessageAdapter, Sample, SERVICES
from openpilot.selfdrive.ui.sunnypilot.mici.korean.projection import project_box
from openpilot.selfdrive.ui.sunnypilot.mici.korean.state import DisplayController, Lead, fresh

EXTRA_SERVICES = frozenset(('modelV2', 'extrinsicsCalibration', 'carOutput', 'vehicleParameters',
                            'narrowRoadCameraState', 'deviceState'))


class LiveInputs:
  def __init__(self):
    self.adapter = MessageAdapter()
    self.controller = DisplayController()
    self.models = {}
    self.received = {}
    self.started_frame = None

  def consume(self, sm, started_frame):
    if started_frame != self.started_frame:
      self.adapter = MessageAdapter()
      self.controller = DisplayController()
      self.models.clear()
      self.received.clear()
      self.started_frame = started_frame
    for name in SERVICES | EXTRA_SERVICES:
      if name not in sm.services or not sm.seen[name]:
        self.adapter.samples.pop(name, None)
        continue
      # Static carParams is valid across the transition; sensors are not.
      if name != 'carParams' and sm.recv_frame[name] < started_frame:
        self.adapter.samples.pop(name, None)
        continue
      signature = (sm.recv_frame[name], bool(sm.valid[name]))
      if self.received.get(name) == signature:
        continue
      self.received[name] = signature
      sample = Sample(sm.recv_time[name], bool(sm.valid[name]), sm[name].to_dict())
      self.adapter.samples[name] = sample
      if name == 'modelV2':
        self.models[sm.logMonoTime[name]] = sample
        if len(self.models) > 16:
          self.models.pop(next(iter(self.models)))

  def get(self, name, now, age=.5):
    sample = self.adapter.samples.get(name)
    return sample if sample and sample.valid and fresh(sample.timestamp, now, age) else None

  def road_ready(self, now, frame_id, camera_eof, *, wide=False):
    model = self.get('modelV2', now, .25)
    calib = self.get('extrinsicsCalibration', now, 1.0)
    device = self.get('deviceState', now, 1.5)
    camera = self.get('narrowRoadCameraState', now, .25)
    if not all((model, calib, device, camera)) or frame_id is None or camera_eof is None:
      return False
    if not fresh(camera_eof / 1e9, now, .25):
      return False
    if not 0 <= (camera_eof - model.data.get('timestampEof', 0)) / 1e9 <= .25:
      return False
    # These sources also affect upstream path length, color and torque. Do
    # not let its last received values decorate a fresh camera indefinitely.
    if not all(self.get(name, now) for name in ('radarState', 'carState', 'carControl', 'carOutput', 'selfdriveState')):
      return False
    lanes, edges = model.data.get('laneLines', []), model.data.get('roadEdges', [])
    if len(lanes) != 4 or len(edges) != 2:
      return False
    for points in [model.data.get('position', {}), *lanes, *edges]:
      xyz = [points.get(axis, []) for axis in ('x', 'y', 'z')]
      if len(xyz[0]) < 2 or any(len(v) != len(xyz[0]) for v in xyz) or not np.isfinite(xyz).all():
        return False
      if np.any(np.diff(xyz[0]) <= 0):
        return False
    for key, count in (('laneLineProbs', 4), ('roadEdgeStds', 2)):
      values = model.data.get(key, [])
      if len(values) != count or not np.isfinite(values).all():
        return False
    values = calib.data.get('rpyCalib', [])
    if calib.data.get('calStatus') != 'calibrated' or len(values) != 3 or not np.isfinite(values).all():
      return False
    if wide:
      values = calib.data.get('wideFromDeviceEuler', [])
      if len(values) != 3 or not np.isfinite(values).all():
        return False
    return True

  def lead(self, now, matrix, frame_id, camera_eof, *, wide=False, camera_offset=0.0):
    # Wide/narrow model capture timing differs; do not reuse a narrow estimate.
    if wide or not self.road_ready(now, frame_id, camera_eof):
      return None
    radar = self.get('radarState', now, .25)
    model = self.models.get(radar.data.get('mdMonoTime')) if radar else None
    if not model or not model.valid or not fresh(model.timestamp, now, .25):
      return None
    camera_age = (camera_eof - model.data.get('timestampEof', 0)) / 1e9
    frame_lag = frame_id - model.data.get('frameId', -1)
    # Live inference trails video. Bound both frame lag and measured capture
    # lag; unlike recorded replay this is not an exact image/model match.
    if not 0 <= frame_lag <= 3 or not 0 <= camera_age <= .15:
      return None
    raw = radar.data.get('leadOne', {})
    if not raw.get('present') or not all(isinstance(raw.get(k), (int, float)) and isfinite(raw[k]) for k in ('dRel', 'yRel', 'vRel')):
      return None
    heights = self.get('extrinsicsCalibration', now, 1.0).data.get('height', [])
    if not heights or not isfinite(heights[0]) or not .5 <= heights[0] <= 3 or not isfinite(camera_offset):
      return None
    matrix = np.asarray(matrix)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
      return None
    path = model.data.get('position', {})
    box = project_box(matrix, raw['dRel'], raw['yRel'] - camera_offset, path.get('x', []), path.get('z', []), heights[0])
    if box is None:
      return None
    return Lead('leadOne', radar.timestamp, raw['dRel'], raw['vRel'], *(float(v) for v in box))

  def display(self, now, *, lead=None, metric=True):
    snapshot, _ = self.adapter.adapt(now)
    snapshot = replace(snapshot, lead=lead)
    state = self.controller.update(snapshot, now)
    if not metric and state.set_speed is not None:
      state = replace(state, set_speed=state.set_speed * .621371)
    return state

  def torque_ready(self, now):
    controls = self.get('controlsState', now)
    if not controls or not self.get('carState', now) or not self.get('carControl', now):
      return False
    lateral = controls.data.get('lateralControlState', {})
    return bool(self.get('vehicleParameters', now)) if 'angleState' in lateral or 'curvatureState' in lateral else bool(self.get('carOutput', now))
