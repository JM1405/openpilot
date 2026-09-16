"""Recorded narrow-camera projection with explicit calibration and frame matching.

The box is an estimated 1.8 m x 1.5 m rear face, not an object detector box.
No default camera, zero calibration or fixed screen position is substituted.
"""
from bisect import bisect_right
import numpy as np

from openpilot.common.transformations.camera import DEVICE_CAMERAS, view_frame_from_device_frame
from openpilot.common.transformations.orientation import rot_from_euler
from openpilot.selfdrive.ui.sunnypilot.mici.korean.messages import Sample
from openpilot.selfdrive.ui.sunnypilot.mici.korean.road import project_road
from openpilot.selfdrive.ui.sunnypilot.mici.korean.state import Lead, fresh

PROJECTION_SERVICES = frozenset(('modelV2', 'radarState', 'extrinsicsCalibration', 'narrowRoadCameraState', 'deviceState'))
VIEWPORT = (476, 240)
RADAR_OFFSET = 1.52  # radard.RADAR_TO_CAMERA, bumper/radar distance -> model mesh frame
LEGACY_HEIGHT = 1.22  # calibrationd.HEIGHT_INIT, explicitly assumed for pre-height archives
VEHICLE_SIZE = (1.8, 1.5)  # display hypothesis, NOT a measured vehicle size


def cover_rect(width, height):
  scale = max(VIEWPORT[0] / width, VIEWPORT[1] / height)
  return ((VIEWPORT[0] - width * scale) / 2, (VIEWPORT[1] - height * scale) / 2, width * scale, height * scale)


def screen_transform(camera, rpy):
  x, y, w, _ = cover_rect(camera.width, camera.height)
  crop = np.array([[w / camera.width, 0, x], [0, w / camera.width, y], [0, 0, 1]])
  return crop @ camera.intrinsics @ view_frame_from_device_frame @ rot_from_euler(rpy)


def project_box(matrix, distance, y_rel, path_x, path_z, height):
  values = np.array([distance, y_rel, height, *path_x, *path_z], dtype=float)
  if not np.isfinite(values).all() or len(path_x) != len(path_z) or len(path_x) < 2:
    return None
  if np.any(np.diff(path_x) <= 0) or not 0 < distance <= 200:
    return None
  forward = distance + RADAR_OFFSET
  if not path_x[0] <= forward <= path_x[-1]:
    return None  # no extrapolated road height
  ground = float(np.interp(forward, path_x, path_z)) + height
  return project_box_at_ground(matrix, distance, y_rel, ground)


def project_box_at_ground(matrix, distance, y_rel, ground):
  """Project a qualified ground height; keep the original viewport/size gates."""
  matrix = np.asarray(matrix)
  if (not np.isfinite([distance, y_rel, ground]).all() or not 0 < distance <= 200 or
      matrix.shape != (3, 3) or not np.isfinite(matrix).all()):
    return None
  forward = distance + RADAR_OFFSET
  width, vehicle_height = VEHICLE_SIZE
  points = np.array([[forward, -y_rel + side * width / 2, ground - up * vehicle_height]
                     for side, up in ((-1, 0), (1, 0), (1, 1), (-1, 1))])
  camera_points = matrix @ points.T
  if not np.isfinite(camera_points).all() or (camera_points[2] <= 1e-6).any():
    return None
  pixels = (camera_points[:2] / camera_points[2]).T
  left, top = pixels.min(axis=0)
  right, bottom = pixels.max(axis=0)
  # Reject out-of-view estimates instead of drawing a guessed edge box.
  if not (0 <= left < right <= VIEWPORT[0] and 0 <= top < bottom <= VIEWPORT[1]):
    return None
  w, h = (right - left) / VIEWPORT[0], (bottom - top) / VIEWPORT[1]
  if w > 0.5 or h > 0.6:
    return None
  return ((left + right) / (2 * VIEWPORT[0]), (top + bottom) / (2 * VIEWPORT[1]), w, h)


class CameraProjection:
  def __init__(self, encode_events, *, image_size, legacy_calibration=False, original_style=False):
    self.legacy_calibration = legacy_calibration
    self.original_style = original_style
    self.image_size = tuple(image_size)
    self.samples = {}
    self.models = {}
    self.catalog = {}
    segments = set()
    for event in encode_events:
      if event.which() != 'narrowRoadEncodeIdx' or not event.valid:
        continue
      idx = event.narrowRoadEncodeIdx
      if str(idx.type) != 'fullHEVC' or idx.timestampEof <= 0:
        raise ValueError('Unsupported camera encoding or timestamps')
      segments.add(idx.segmentNum)
      if idx.frameId in self.catalog:
        raise ValueError('Duplicate camera frame ID')
      self.catalog[idx.frameId] = {'frame_id': idx.frameId, 'file_index': idx.segmentId,
                                   'capture_timestamp': idx.timestampEof / 1e9}
    entries = sorted(self.catalog.values(), key=lambda x: x['file_index'])
    if len(segments) != 1 or [e['file_index'] for e in entries] != list(range(len(entries))):
      raise ValueError('A single complete video segment is required')
    self.entries = entries
    self.capture_times = [e['capture_timestamp'] for e in entries]
    if any(b <= a for a, b in zip(self.capture_times, self.capture_times[1:], strict=False)):
      raise ValueError('Camera timestamps are not increasing')

  def consume(self, event):
    service = event.which()
    if service not in PROJECTION_SERVICES:
      return
    sample = Sample(event.logMonoTime / 1e9, bool(event.valid), getattr(event, service).to_dict())
    old = self.samples.get(service)
    if old is None or sample.timestamp >= old.timestamp:
      self.samples[service] = sample
    if service == 'modelV2':
      self.models[event.logMonoTime] = sample
      if len(self.models) > 64:
        self.models.pop(min(self.models))

  def get(self, name, now, age):
    sample = self.samples.get(name)
    return sample if sample and sample.valid and fresh(sample.timestamp, now, age) else None

  def at(self, now, *, allow_lead):
    info = {'reason': 'camera_unavailable', 'road': None, 'box_size_assumption_m': VEHICLE_SIZE,
            'radar_offset_m': RADAR_OFFSET, 'calibration_profile': 'legacy_deprecated' if self.legacy_calibration else 'current'}
    camera_state = self.get('narrowRoadCameraState', now, 0.25)
    if camera_state is None:
      return None, None, info
    i = bisect_right(self.capture_times, now) - 1
    if i < 0 or not fresh(self.capture_times[i], now, 0.25):
      return None, None, info
    image = dict(self.entries[i])
    radar = self.get('radarState', now, 0.25)
    model = self.models.get(radar.data['mdMonoTime']) if radar else None
    radar_matched = bool(model and model.valid and fresh(model.timestamp, now, 0.25))
    if not radar_matched:
      # Road perception is independent of a tracked lead or radar availability.
      model = self.get('modelV2', now, 0.25)
    if model and model.valid and fresh(model.timestamp, now, 0.25):
      matched = self.catalog.get(model.data['frameId'])
      if matched and fresh(matched['capture_timestamp'], now, 0.25):
        image = dict(matched)
      else:
        model = None
    else:
      model = None
    device = self.get('deviceState', now, 1.5)
    key = (device.data['deviceType'] if device else 'unknown', camera_state.data['sensor'])
    cameras = DEVICE_CAMERAS.get(key)
    # Unknown device + known AR/OX sensor is an explicitly supported legacy source combination.
    camera = cameras.narrow_road if cameras else None
    if camera is None or camera.size != self.image_size:
      info['reason'] = 'camera_model_mismatch'
      return None, None, info
    image['rect'] = cover_rect(*self.image_size)
    info.update(camera_key=key, image_frame_id=image['frame_id'], image_age=now - image['capture_timestamp'])
    if model is None:
      info['reason'] = 'model_frame_unmatched'
      return image, None, info
    info.update(model_frame_id=model.data['frameId'], model_timestamp=model.timestamp,
                radar_timestamp=radar.timestamp if radar else None)
    calibration = self.get('extrinsicsCalibration', now, 1.0)
    if calibration is None:
      info['reason'] = 'calibration_unavailable'
      return image, None, info
    data = calibration.data
    calibrated = data.get('deprecated', {}).get('calStatus') == 1 if self.legacy_calibration else data.get('calStatus') == 'calibrated'
    rpy = data.get('rpyCalib', [])
    if not calibrated or len(rpy) != 3 or not np.isfinite(rpy).all():
      info['reason'] = 'calibration_invalid'
      return image, None, info
    heights = data.get('height', [])
    height = heights[0] if heights else LEGACY_HEIGHT if self.legacy_calibration else None
    if height is None or not np.isfinite(height) or not 0.5 <= height <= 3:
      info['reason'] = 'height_unavailable'
      return image, None, info
    matrix = screen_transform(camera, rpy)
    info.update(calibration_timestamp=calibration.timestamp, rpy=rpy, height_m=height,
                height_source='recorded' if heights else 'legacy_assumption', transform=matrix.tolist(),
                road=project_road(matrix, model.data, height))
    if self.original_style:
      from openpilot.selfdrive.ui.sunnypilot.mici.korean.mici_road import project_mici_road
      distance = radar.data['leadOne']['dRel'] if radar_matched and allow_lead else None
      info['road'] = project_mici_road(matrix, model.data, height, distance)
    if not allow_lead:
      info['reason'] = 'lead_unavailable'
      return image, None, info
    if not radar_matched:
      info['reason'] = 'model_frame_unmatched'
      return image, None, info
    lead_data = radar.data['leadOne']
    path = model.data['position']
    box = project_box(matrix, lead_data['dRel'], lead_data['yRel'], path['x'], path['z'], height)
    if box is None:
      info['reason'] = 'projection_out_of_view_or_invalid'
      return image, None, info
    x, y, width, box_height = (float(v) for v in box)
    lead = Lead('leadOne', radar.timestamp, lead_data['dRel'], lead_data['vRel'], x, y, width, box_height)
    info['reason'] = 'projected_estimate'
    return image, lead, info
