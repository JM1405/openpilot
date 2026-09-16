"""Actual MICI camera view with our HUD; no PC replay/scenario imports."""
import time
import numpy as np
import pyray as rl
from openpilot.common.transformations.camera import DEVICE_CAMERAS
from opendbc.car.structs import car

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.mici.onroad.augmented_road_view import AugmentedRoadView, WIDE_CAM
from openpilot.selfdrive.ui.mici.onroad.cameraview import CameraView
from openpilot.selfdrive.ui.mici.onroad.torque_bar import TorqueBar
from openpilot.selfdrive.ui.sunnypilot.mici.korean import drawing
from openpilot.selfdrive.ui.sunnypilot.mici.korean.live import LiveInputs
from openpilot.selfdrive.ui.sunnypilot.mici.korean.native_alerts import KoreanAlertRenderer
from openpilot.selfdrive.ui.sunnypilot.mici.korean.renderer import KoreanHudRenderer


class KoreanAugmentedRoadView(AugmentedRoadView):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._inputs = LiveInputs()
    self._korean_hud = KoreanHudRenderer()
    self._alert_renderer = KoreanAlertRenderer()
    self._torque_bar = TorqueBar()
    self._calibration_frame = None

  def is_swiping_left(self):
    # The product excludes the bookmark feature. Tap-to-home still uses the
    # inherited mouse-release handler and callback; no bookmark is rendered.
    return False

  def _update_calibration(self):
    sm = ui_state.sm
    key = (str(sm['deviceState'].deviceType), str(sm['narrowRoadCameraState'].sensor))
    camera = DEVICE_CAMERAS.get(key)
    if camera is not self.device_camera:
      self._matrix_cache_key = None
    self.device_camera = camera
    # Camera preview may use the upstream fallback crop, but road/lead
    # overlays are gated off for an unknown device/sensor pair.
    calib = sm['extrinsicsCalibration']
    values = [*calib.rpyCalib, *calib.wideFromDeviceEuler]
    if camera is not None and np.isfinite(values).all():
      super()._update_calibration()
      if (sm.updated['extrinsicsCalibration'] and sm.valid['extrinsicsCalibration'] and
          str(calib.calStatus) == 'calibrated' and len(calib.rpyCalib) == 3):
        self._calibration_frame = sm.recv_frame['extrinsicsCalibration']

  def _render(self, _):
    if not ui_state.started:
      rl.draw_rectangle_rec(self.rect, rl.BLACK)
      self._offroad_label.render(self.rect)
      return
    now = time.monotonic()
    self._inputs.consume(ui_state.sm, ui_state.started_frame)
    self._switch_stream_if_needed(ui_state.sm)
    self._update_calibration()
    self._content_rect = rl.Rectangle(self.rect.x, self.rect.y, self.rect.width - 60, self.rect.height)
    rl.begin_scissor_mode(int(self.rect.x), int(self.rect.y), int(self.rect.width), int(self.rect.height))
    try:
      # Original VisionIPC camera and its calibration/zoom transform. It also
      # updates the original ModelRenderer's projection matrix for this view.
      CameraView._render(self, self._content_rect)
      frame_id = self.frame.frame_id if self.frame is not None else None
      camera_eof = self.client.timestamp_eof if self.frame is not None else None
      wide = self.stream_type == WIDE_CAM
      calibrated = self._calibration_frame == ui_state.sm.recv_frame['extrinsicsCalibration']
      ready = calibrated and self.device_camera is not None and self._inputs.road_ready(now, frame_id, camera_eof, wide=wide)
      if ready:
        self._model_renderer.render(self._content_rect)
        rl.draw_texture_ex(self._fade_texture, rl.Vector2(self.rect.x, self.rect.y), 0, 1, rl.WHITE)
      lead = self._inputs.lead(now, self._model_renderer._car_space_transform, frame_id, camera_eof,
                               wide=wide, camera_offset=self._model_renderer._camera_offset) if ready else None
      state = self._inputs.display(now, lead=lead, metric=ui_state.is_metric)

      # Preserve the native warning owner, including startup/unresponsive
      # alerts and their fade. Do not substitute the PC 0.5s alert lifetime.
      alert, clearing = self._alert_renderer.will_render()
      show_warning = alert is not None
      required = show_warning and not clearing and alert.visual_alert == car.CarControl.HUDControl.VisualAlert.steerRequired

      if not show_warning and self._inputs.torque_ready(now):
        self._torque_bar.render(self._content_rect)
      # Existing optional BSD indication is retained, never converted into a
      # surrounding-vehicle detector or an automatic lane-change permission.
      bsd = getattr(self._hud_renderer, 'blind_spot_indicators', None)
      if bsd is not None:
        bsd.update()
        if not show_warning and not state.stale:
          bsd.render(self._content_rect)

      drawing.begin_frame()
      self._korean_hud.render(state, suppress_road=show_warning, wheel_critical=required)
      drawing.render_native(drawing.commands(), offset=(self.rect.x, self.rect.y))
      # Our HUD scissor ends; restore native clipping before the original
      # alert renderer so warnings cannot spill into the sidebar while swiping.
      rl.begin_scissor_mode(int(self._content_rect.x), int(self._content_rect.y),
                            int(self._content_rect.width), int(self._content_rect.height))
      self._alert_renderer.render(self._content_rect)
    finally:
      rl.end_scissor_mode()
