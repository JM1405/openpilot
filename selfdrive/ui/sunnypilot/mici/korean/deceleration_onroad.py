"""Opt-in badge on the original MICI view; original alerts retain ownership."""
import os
import time
import numpy as np

from openpilot.common.transformations.camera import DEVICE_CAMERAS
from openpilot.selfdrive.ui.mici.onroad.augmented_road_view import AugmentedRoadView, NARROW_ROAD_CAM, WIDE_CAM
from openpilot.selfdrive.ui.mici.onroad.model_renderer import ModelRenderer
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing
from openpilot.selfdrive.ui.sunnypilot.mici.korean.deceleration import DecelerationMonitor
from openpilot.selfdrive.ui.sunnypilot.mici.korean.driving_status import DrivingStatusMonitor
from openpilot.selfdrive.ui.sunnypilot.mici.korean.native_driving import DrivingHudRenderer
from openpilot.selfdrive.ui.sunnypilot.mici.korean.lead_marker import LeadMarkerMonitor, marker_commands


class LeadModelRenderer(ModelRenderer):
  """Keep the candidate below the original fade, warnings, HUD and borders."""
  def __init__(self, draw_lead):
    super().__init__()
    self.draw_lead = draw_lead

  def _render(self, rect):
    super()._render(rect)
    self.draw_lead(rect)


def badge_commands(status, width, height):
  # Top right leaves the original MAX/DM area (left), torque arc, steering/model
  # icons (bottom) and confidence sidebar untouched on the 536 x 240 MICI view.
  drawing.begin_frame()
  if width < 460 or height < 230:
    return []
  x, y, w = width - 266, 14, 252
  drawing.draw_rectangle_rounded(drawing.Rectangle(x, y, w, 56), .25, 8, drawing.Color(12, 18, 24, 225))
  color = drawing.Color(107, 226, 198, 255) if getattr(status, 'selected', False) else drawing.Color(225, 229, 234, 255)
  if getattr(status, 'warning', False):
    color = drawing.Color(255, 190, 90, 255)
  drawing.alert_text(status.title, x + 12, y + 25, 20, color, 20)
  if status.detail:
    detail_color = color if getattr(status, 'warning', False) else drawing.Color(202, 208, 216, 255)
    drawing.alert_text(status.detail, x + 12, y + 46, 15, detail_color, 15)
  return drawing.commands()


class NoBookmark:
  # Discomfort bookmarks are excluded from this product. Preserve inherited tap
  # navigation without drawing/handling the upstream bookmark swipe widget.
  def render(self, rect):
    pass

  def interacting(self):
    return False

  def is_swiping_left(self):
    return False


class DrivingStatusAugmentedRoadView(AugmentedRoadView):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._driving = DrivingStatusMonitor()
    self._deceleration = None
    self._hud_renderer = DrivingHudRenderer()
    self._bookmark_icon = NoBookmark()
    self._lead = LeadMarkerMonitor(continuity=os.getenv('KOREAN_LEAD_CONTINUITY', '0') == '1',
                                   source_aware=os.getenv('KOREAN_LEAD_SOURCE', '0') == '1',
                                   ground_aware=os.getenv('KOREAN_LEAD_GROUND', '0') == '1')
    self._lead_calibration = None
    self._lead_camera_key = None
    self._lead_warning = False
    # Recorded frame 4275 exposes a lingering model candidate after a turn.
    # Keep the wide extension separately opt-in until visual quality is resolved.
    self._wide_lead = os.getenv('KOREAN_WIDE_LEAD', '0') == '1'
    self._model_renderer = LeadModelRenderer(self._render_lead)

  def _update_calibration(self):
    sm = ui_state.sm
    key = (str(sm['deviceState'].deviceType), str(sm['narrowRoadCameraState'].sensor))
    camera = DEVICE_CAMERAS.get(key)
    if camera is not self.device_camera:
      self._matrix_cache_key = None
      self._lead_calibration = None
    self.device_camera = camera
    self._lead_camera_key = key if camera is not None else None
    calib = sm['extrinsicsCalibration']
    if camera is None or len(calib.rpyCalib) != 3 or not np.isfinite([*calib.rpyCalib, *calib.wideFromDeviceEuler]).all():
      self._lead_calibration = None
      return
    super()._update_calibration()
    if sm.updated['extrinsicsCalibration'] and sm.valid['extrinsicsCalibration'] and str(calib.calStatus) == 'calibrated':
      self._lead_calibration = (sm.recv_frame['extrinsicsCalibration'], sm.logMonoTime['extrinsicsCalibration'])

  def _render_lead(self, rect):
    marker = self._lead.update(
      ui_state.sm, time.monotonic(), started=ui_state.started, started_frame=ui_state.started_frame,
      started_time=ui_state.started_time, matrix=self._model_renderer._car_space_transform,
      frame_id=self.frame.frame_id if self.frame else None,
      camera_eof=self.client.timestamp_eof if self.frame else None,
      camera_size=(self.frame.width, self.frame.height) if self.frame else (0, 0),
      camera_key=self._lead_camera_key, applied_calibration=self._lead_calibration,
      narrow=self.stream_type == NARROW_ROAD_CAM, connected=self.client.is_connected(), switching=self._switching,
      camera_offset=self._model_renderer._camera_offset, viewport=(rect.width, rect.height),
      dual_camera=NARROW_ROAD_CAM in self.available_streams and WIDE_CAM in self.available_streams)
    # Consume even while a warning is present. A warning that begins during
    # rendering is still painted above this layer by the original view.
    if (self.stream_type == NARROW_ROAD_CAM or self._wide_lead) and not self._lead_warning and self._alert_renderer.will_render()[0] is None:
      items = marker_commands(marker)
      if items:
        drawing.render_native(items, offset=(rect.x, rect.y))

  def _render(self, rect):
    warning_before = self._alert_renderer.will_render()[0] if ui_state.started else None
    self._lead_warning = warning_before is not None
    now = time.monotonic()
    driving = self._driving.update(ui_state.sm, now, started=ui_state.started, started_frame=ui_state.started_frame,
                                    started_time=ui_state.started_time, CP=ui_state.CP)
    self._hud_renderer.driving_status = driving
    super()._render(rect)
    if not ui_state.started:
      return
    # Do consume during warnings so replay guards and driver transitions cannot
    # be bypassed by waiting for the warning/fade to finish.
    status = driving
    if self._deceleration is not None:
      reason = self._deceleration.update(ui_state.sm, now, started_frame=ui_state.started_frame,
                                        started_time=ui_state.started_time,
                                        openpilot_longitudinal=ui_state.CP.openpilotLongitudinalControl if ui_state.CP else None,
                                        metric=ui_state.is_metric, driving_active=driving.state == 'active')
      if driving.state == 'active':
        status = reason
    if warning_before is not None or self._alert_renderer.will_render()[0] is not None:
      return
    items = badge_commands(status, self._content_rect.width, self._content_rect.height)
    drawing.render_native(items, offset=(self._content_rect.x, self._content_rect.y))


class RoadReasonAugmentedRoadView(DrivingStatusAugmentedRoadView):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.runtime import control_enabled
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.deceleration import ControlDecelerationMonitor
    self._deceleration = ControlDecelerationMonitor() if control_enabled() else DecelerationMonitor()
