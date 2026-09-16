"""Read-only, camera-matched leadOne candidate. No target identity or control claim.

The white corners use measured calibration and an estimated 1.8 x 1.5 m rear
face. PreviewAttention's unvalidated red thresholds are deliberately not used.
"""
from dataclasses import dataclass
import math

import numpy as np

from openpilot.common.transformations.camera import DEVICE_CAMERAS
from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing
from openpilot.selfdrive.ui.sunnypilot.mici.korean.lead_continuity import LeadContinuityGate, LeadObservation
from openpilot.selfdrive.ui.sunnypilot.mici.korean.lead_ground import ground_height
from openpilot.selfdrive.ui.sunnypilot.mici.korean.lead_source import LeadSourceGate
from openpilot.selfdrive.ui.sunnypilot.mici.korean.projection import project_box, project_box_at_ground, VIEWPORT
from openpilot.selfdrive.ui.sunnypilot.mici.korean.state import Lead

LEASES = {'carState': .15, 'radarState': .25, 'modelV2': .25, 'extrinsicsCalibration': 1.,
          'deviceState': 1.5, 'narrowRoadCameraState': .25, 'wideRoadCameraState': .25}
CAMERAS = ('narrowRoadCameraState', 'wideRoadCameraState')


@dataclass(frozen=True)
class LeadMarker:
  lead: Lead | None = None
  reason: str = 'waiting'
  ground_source: str = 'none'
  ground_reason: str = 'not_evaluated'


class LeadMarkerMonitor:
  def __init__(self, *, continuity=False, source_aware=False, ground_aware=False):
    self.source_aware = source_aware
    self.ground_aware = bool(ground_aware and source_aware)
    self.continuity = LeadSourceGate() if source_aware else (LeadContinuityGate() if continuity else None)
    self.drive = None
    self.received = {}
    self.high_water = {}
    self.accepted = {}
    self.models = {}
    self.camera_high_water = {}
    self.camera_signature = {}
    self.camera_accepted = {}
    self.captures = {name: {} for name in CAMERAS}
    self.capture_water = dict.fromkeys(CAMERAS, (-1, 0))
    self.capture_signature = {}
    self.stream = None
    self.switch_after = 0

  def _read(self, sm, name, now, start_frame, start_time):
    lease = LEASES[name]

    def fresh(t):
      return math.isfinite(t) and t > 0 and start_time <= t <= now and now - t <= lease

    if name not in sm.services or not sm.seen[name]:
      self.accepted[name] = False
      return None
    frame, stamp, received = sm.recv_frame[name], sm.logMonoTime[name], sm.recv_time[name]
    signature = (frame, stamp, bool(sm.valid[name]))
    if self.received.get(name) != signature:
      old_frame, old_stamp = self.high_water.get(name, (-1, 0))
      timely = fresh(stamp / 1e9) and fresh(received)
      self.accepted[name] = bool(sm.valid[name] and timely and frame >= start_frame and
                                 frame > old_frame and stamp > old_stamp)
      if timely:
        self.high_water[name] = (max(frame, old_frame), max(stamp, old_stamp))
      self.received[name] = signature
    if not self.accepted.get(name) or not fresh(stamp / 1e9) or not fresh(received):
      return None
    return sm[name]

  def _capture(self, sm, name, message, now, start_time):
    """Cache explicit per-camera metadata; never infer wide EOF from narrow EOF."""
    records = self.captures[name]
    if message is None:
      records.clear()
      return
    signature = (sm.recv_frame[name], sm.logMonoTime[name])
    if signature != self.capture_signature.get(name):
      self.capture_signature[name] = signature
      previous_id, previous_eof = self.capture_water[name]
      valid = (message.frameId > previous_id and message.timestampEof > previous_eof and
               0 < message.timestampSof <= message.timestampEof <= sm.logMonoTime[name] and
               start_time <= message.timestampSof / 1e9 and now - message.timestampEof / 1e9 <= .25)
      if not valid:
        records.clear()
        return
      self.capture_water[name] = (message.frameId, message.timestampEof)
      records[message.frameId] = (message.timestampSof, message.timestampEof, str(message.sensor))
    self.captures[name] = {key: value for key, value in records.items() if now - value[1] / 1e9 <= .25}
    while len(self.captures[name]) > 16:
      self.captures[name].pop(next(iter(self.captures[name])))

  def update(self, sm, now, *, started, started_frame, started_time, matrix, frame_id, camera_eof,
             camera_size, camera_key, applied_calibration, narrow=True, connected=True, switching=False,
             camera_offset=0., viewport=VIEWPORT, dual_camera=False):
    drive = (started, started_frame, started_time)
    if self.drive != drive:
      self.__init__(continuity=self.continuity is not None, source_aware=self.source_aware, ground_aware=self.ground_aware)
      self.drive = drive
    if not started or not math.isfinite(now):
      return LeadMarker(reason='offroad')
    messages = {name: self._read(sm, name, now, started_frame, started_time) for name in LEASES}
    model = messages['modelV2']
    if model is None:
      self.models.clear()
    else:
      stamp = sm.logMonoTime['modelV2']
      if stamp not in self.models:
        self.models[stamp] = (model.to_dict(), sm.recv_time['modelV2'])
      self.models = {k: v for k, v in self.models.items() if now - k / 1e9 <= .25 and now - v[1] <= .25}
      while len(self.models) > 16:
        self.models.pop(next(iter(self.models)))
    # Consume matched model observations before camera/warning suppression.
    # A camera switch or repeated 60 Hz redraw is not a new target observation.
    continuity_reason = 'candidate'
    visual_lateral = None
    if self.continuity is not None:
      radar, cs = messages['radarState'], messages['carState']
      paired = self.models.get(radar.mdMonoTime) if radar is not None else None
      if (paired is None or cs is None or not cs.canValid or cs.canTimeout or
          not math.isfinite(cs.vEgo) or cs.vEgo < 0):
        continuity_reason = self.continuity.invalidate()
      else:
        data, raw = paired[0], radar.leadOne
        if self.source_aware:
          decision = self.continuity.update_source(raw, data, radar.mdMonoTime)
          continuity_reason, visual_lateral = decision.reason, decision.lateral
        else:
          continuity_reason = self.continuity.update(LeadObservation(
            radar.mdMonoTime, data.get('frameId', -1), data.get('timestampEof', 0), raw.present,
            raw.dRel, raw.yRel, raw.vRel, raw.modelProb))
    for name in CAMERAS:
      self._capture(sm, name, messages[name], now, started_time)
    required = set(LEASES) - ({'wideRoadCameraState'} if narrow else set())
    if any(messages[name] is None for name in required):
      return LeadMarker(reason='input_unavailable')
    # Only this exact native viewport is supported by project_box. Do not
    # stretch coordinates from a different layout.
    if switching or not connected or tuple(viewport) != VIEWPORT or (not narrow and not dual_camera):
      return LeadMarker(reason='camera_unavailable')
    expected_key = (str(messages['deviceState'].deviceType), str(messages['narrowRoadCameraState'].sensor))
    config = DEVICE_CAMERAS.get(expected_key)
    camera = (config.narrow_road if narrow else config.wide_road) if config else None
    if (camera is None or 'unknown' in expected_key or camera_key != expected_key or
        tuple(camera_size) != camera.size or
        (not narrow and str(messages['wideRoadCameraState'].sensor) != expected_key[1])):
      return LeadMarker(reason='camera_geometry')
    if frame_id is None or camera_eof is None or camera_eof <= 0 or not 0 <= now - camera_eof / 1e9 <= .25:
      return LeadMarker(reason='camera_timing')
    signature = (frame_id, camera_eof)
    if signature != self.camera_signature.get(narrow):
      previous_frame, previous_eof = self.camera_high_water.get(narrow, (-1, 0))
      self.camera_accepted[narrow] = frame_id > previous_frame and camera_eof > previous_eof
      self.camera_high_water[narrow] = (max(frame_id, previous_frame), max(camera_eof, previous_eof))
      self.camera_signature[narrow] = signature
    if self.stream is not None and self.stream != narrow:
      self.switch_after = max(self.switch_after, self.camera_high_water.get(self.stream, (-1, 0))[1])
    self.stream = narrow
    if not self.camera_accepted.get(narrow) or camera_eof / 1e9 < started_time or camera_eof <= self.switch_after:
      return LeadMarker(reason='camera_replayed')
    calib = messages['extrinsicsCalibration']
    if (applied_calibration != (sm.recv_frame['extrinsicsCalibration'], sm.logMonoTime['extrinsicsCalibration']) or
        str(calib.calStatus) != 'calibrated' or len(calib.rpyCalib) != 3 or not np.isfinite(calib.rpyCalib).all() or
        not calib.height or not math.isfinite(calib.height[0]) or not .5 <= calib.height[0] <= 3):
      return LeadMarker(reason='calibration_unavailable')
    if not narrow and (len(calib.wideFromDeviceEuler) != 3 or not np.isfinite(calib.wideFromDeviceEuler).all()):
      return LeadMarker(reason='wide_calibration_unavailable')
    cs, radar = messages['carState'], messages['radarState']
    if not cs.canValid or cs.canTimeout or not math.isfinite(cs.vEgo) or cs.vEgo < 0:
      return LeadMarker(reason='vehicle_unavailable')
    paired = self.models.get(radar.mdMonoTime)
    if paired is None:
      return LeadMarker(reason='model_unmatched')
    data = paired[0]
    model_frame, model_eof = data.get('frameId', -1), data.get('timestampEof', 0)
    if not narrow:
      main = self.captures[CAMERAS[0]].get(model_frame)
      extra = self.captures[CAMERAS[1]].get(data.get('frameIdExtra', 0))
      if (main is None or extra is None or main[1] != model_eof or abs(main[0] - extra[0]) > 10_000_000 or
          main[2] != expected_key[1] or extra[2] != expected_key[1] or extra[1] > radar.mdMonoTime or
          extra[1] / 1e9 < started_time):
        return LeadMarker(reason='wide_model_unmatched')
      model_frame, model_eof = data['frameIdExtra'], extra[1]
    if (not started_time <= data.get('timestampEof', 0) / 1e9 <= radar.mdMonoTime / 1e9 or
        not 0 <= frame_id - model_frame <= 3 or not 0 <= (camera_eof - model_eof) / 1e9 <= .15):
      return LeadMarker(reason='model_camera_lag')
    raw = radar.leadOne
    if not raw.present or not all(math.isfinite(v) for v in (raw.dRel, raw.yRel, raw.vRel, camera_offset)):
      return LeadMarker(reason='lead_unavailable')
    if continuity_reason != 'candidate':
      return LeadMarker(reason=continuity_reason)
    matrix = np.asarray(matrix)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
      return LeadMarker(reason='projection_unavailable')
    path = data.get('position', {})
    lateral = visual_lateral if self.source_aware else raw.yRel
    ground_source, ground_reason = 'path', 'candidate'
    if self.ground_aware:
      # Bracket the unshifted model target in model coordinates. Camera offset
      # belongs only to screen projection, not to lane/lead association.
      ground = ground_height(data, raw.dRel, lateral, calib.height[0])
      ground_source, ground_reason = ground.source, ground.reason
      box = (project_box_at_ground(matrix, raw.dRel, lateral - camera_offset, ground.z)
             if ground.z is not None else None)
    else:
      box = project_box(matrix, raw.dRel, lateral - camera_offset, path.get('x', []), path.get('z', []), calib.height[0])
    if box is None:
      return LeadMarker(reason='projection_unavailable', ground_source=ground_source, ground_reason=ground_reason)
    # leadOne is a slot, not a persistent object ID. Recompute every frame;
    # never smooth positions or carry attention/color across a target switch.
    lead = Lead('leadOne', sm.logMonoTime['radarState'] / 1e9, raw.dRel, raw.vRel, *(float(v) for v in box))
    return LeadMarker(lead, 'candidate', ground_source, ground_reason)


def marker_commands(marker):
  drawing.begin_frame()
  if marker.lead is None:
    return []
  lead = marker.lead
  x, y, w, h = lead.x * VIEWPORT[0], lead.y * VIEWPORT[1], lead.width * VIEWPORT[0], lead.height * VIEWPORT[1]
  length = min(12, w * .22, h * .22)
  # Too small to distinguish four open corners; don't enlarge an estimated
  # vehicle or pin it to the screen edge to manufacture visibility.
  if min(w, h) < 12 or min(x - w / 2, y - h / 2, VIEWPORT[0] - x - w / 2, VIEWPORT[1] - y - h / 2) < 3:
    return []
  for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
    px, py = x + dx * w / 2, y + dy * h / 2
    for color, weight in ((drawing.Color(10, 15, 20, 210), 5), (drawing.WHITE, 2.5)):
      drawing.draw_line_ex(drawing.Vector2(px, py), drawing.Vector2(px - dx * length, py), weight, color)
      drawing.draw_line_ex(drawing.Vector2(px, py), drawing.Vector2(px, py - dy * length), weight, color)
  return drawing.commands()
