"""Koranipilot 2.0 comma four (mici 536x240) QR pairing page & onroad deceleration badge."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pyray as rl
import qrcode

from openpilot.common.basedir import BASEDIR
from openpilot.system.ui.lib.application import FontWeight, MousePos, gui_app
from openpilot.system.ui.widgets.nav_widget import NavWidget
from openpilot.sunnypilot.koranipilot import DEFAULT_WEB_PORT
from openpilot.sunnypilot.koranipilot.config import CachedJsonFile, active_state_path, load_config, nav_state_path
from openpilot.sunnypilot.koranipilot.net import get_lan_ip
from openpilot.sunnypilot.koranipilot.server import summarize_nav

FONT_PATH = Path(BASEDIR) / "sunnypilot" / "koranipilot" / "fonts" / "AlertSans.ttf"

_SEED_CHARS = (
  "고라니웹리모컨포트폰내비연결됨카메라로QR스캔닫기방지턱급커브과속구간단속감속중핫스팟와이파이연결필요대기상태kmhm·:"
  + "".join(chr(c) for c in range(32, 127))
)

_ko_font: rl.Font | None = None
_ko_chars: set[str] = set()
_ko_font_failed = False


def _get_ko_font(text: str) -> rl.Font:
  global _ko_font, _ko_chars, _ko_font_failed
  if _ko_font_failed or not FONT_PATH.is_file():
    return gui_app.font(FontWeight.UNIFONT)

  needed = set(text)
  if _ko_font is None or not needed <= _ko_chars:
    try:
      _ko_chars.update(_SEED_CHARS)
      _ko_chars.update(needed)
      codepoints = sorted({ord(ch) for ch in _ko_chars})
      if _ko_font is not None and _ko_font.texture.id != 0:
        rl.unload_font(_ko_font)
      buf = rl.ffi.new("int[]", codepoints)
      _ko_font = rl.load_font_ex(str(FONT_PATH), 40, rl.ffi.cast("int *", buf), len(codepoints))
      rl.set_texture_filter(_ko_font.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
    except Exception:
      _ko_font_failed = True
      return gui_app.font(FontWeight.UNIFONT)
  return _ko_font


def _measure_ko(text: str, font_size: float) -> rl.Vector2:
  font = _get_ko_font(text)
  return rl.measure_text_ex(font, text, float(font_size), 0.0)


def _draw_ko(text: str, x: float, y: float, font_size: float, color: rl.Color) -> None:
  font = _get_ko_font(text)
  raw_draw = getattr(rl, "_orig_draw_text_ex", rl.draw_text_ex)
  raw_draw(font, text, rl.Vector2(float(x), float(y)), float(font_size), 0.0, color)


class KoraniQrPage(NavWidget):
  """1-tap QR remote & connection status screen on comma four (536x240)."""

  def __init__(self):
    super().__init__()
    self._qr_texture: rl.Texture | None = None
    self._qr_url: str | None = None
    self._lan_ip: str | None = None
    self._last_net_check = float("-inf")
    self._nav_reader = CachedJsonFile(nav_state_path)
    self._close_rect = rl.Rectangle(18, 178, 120, 44)

  def _refresh_ip_and_qr(self) -> None:
    now = time.monotonic()
    if now - self._last_net_check < 2.0:
      return
    self._last_net_check = now
    self._lan_ip = get_lan_ip()
    target_url = f"http://{self._lan_ip}:{DEFAULT_WEB_PORT}" if self._lan_ip else None
    if target_url != self._qr_url:
      self._qr_url = target_url
      self._rebuild_qr_texture(target_url)

  def _rebuild_qr_texture(self, url: str | None) -> None:
    if self._qr_texture and self._qr_texture.id != 0:
      rl.unload_texture(self._qr_texture)
      self._qr_texture = None
    if not url:
      return
    try:
      qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=8,
        border=2,
      )
      qr.add_data(url)
      qr.make(fit=True)
      pil_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
      img_array = np.array(pil_img, dtype=np.uint8)
      rl_image = rl.Image()
      rl_image.data = rl.ffi.cast("void *", img_array.ctypes.data)
      rl_image.width = pil_img.width
      rl_image.height = pil_img.height
      rl_image.mipmaps = 1
      rl_image.format = rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8
      self._qr_texture = rl.load_texture_from_image(rl_image)
    except Exception:
      self._qr_texture = None

  def show_event(self):
    super().show_event()
    self._last_net_check = float("-inf")

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if self.is_dismissing:
      return
    close_rect = rl.Rectangle(self._rect.x + 18, self._rect.y + 178, 120, 44)
    if rl.check_collision_point_rec(mouse_pos, close_rect):
      self.dismiss()
      return
    super()._handle_mouse_release(mouse_pos)

  def _render(self, rect: rl.Rectangle):
    self._refresh_ip_and_qr()

    ox = self._rect.x
    oy = self._rect.y
    accent = rl.Color(92, 224, 168, 255)
    muted = rl.Color(175, 190, 184, 255)
    card_bg = rl.Color(26, 38, 34, 255)

    # Left column: Korean guide + live phone status + close button
    _draw_ko("고라니 웹 리모컨", ox + 18, oy + 20, 30, rl.WHITE)

    if self._qr_url:
      _draw_ko(self._qr_url, ox + 18, oy + 62, 24, accent)
      _draw_ko("폰 카메라로 QR 스캔", ox + 18, oy + 96, 20, muted)
    else:
      _draw_ko("Wi-Fi / 핫스팟 연결 필요", ox + 18, oy + 64, 24, rl.Color(245, 185, 66, 255))
      _draw_ko("연결 후 자동 표시돼요", ox + 18, oy + 96, 20, muted)

    nav_summary = summarize_nav(self._nav_reader.read(), time.monotonic())
    pill_rect = rl.Rectangle(ox + 18, oy + 128, 260, 36)
    rl.draw_rectangle_rounded(pill_rect, 0.45, 8, card_bg)
    if nav_summary["fresh"]:
      mode_label = "길안내" if nav_summary["mode"] == "route" else "안전운전"
      _draw_ko(f"폰 내비 연결됨 · {mode_label}", ox + 30, oy + 135, 20, accent)
    else:
      _draw_ko("폰 내비 앱 대기 중", ox + 30, oy + 135, 20, muted)

    close_rect = rl.Rectangle(ox + 18, oy + 178, 120, 44)
    self._close_rect = close_rect
    rl.draw_rectangle_rounded(close_rect, 0.35, 8, rl.Color(42, 56, 50, 255))
    rl.draw_rectangle_rounded_lines_ex(close_rect, 0.35, 8, 2, rl.Color(92, 224, 168, 180))
    _draw_ko("닫기", ox + 55, oy + 187, 24, rl.WHITE)

    # Right column: QR code (536 - 204 - 16 = 316)
    qr_size = 204.0
    qr_x = ox + self._rect.width - qr_size - 16
    qr_y = oy + (self._rect.height - qr_size) / 2.0
    if self._qr_texture and self._qr_texture.id != 0:
      src = rl.Rectangle(0, 0, float(self._qr_texture.width), float(self._qr_texture.height))
      dst = rl.Rectangle(qr_x, qr_y, qr_size, qr_size)
      rl.draw_texture_pro(self._qr_texture, src, dst, rl.Vector2(0, 0), 0.0, rl.WHITE)
    else:
      box = rl.Rectangle(qr_x, qr_y, qr_size, qr_size)
      rl.draw_rectangle_rounded(box, 0.12, 8, card_bg)
      rl.draw_rectangle_rounded_lines_ex(box, 0.12, 8, 2, rl.Color(60, 82, 74, 255))
      _draw_ko("QR 대기 중", qr_x + 48, qr_y + 88, 22, muted)

  def __del__(self):
    if self._qr_texture and self._qr_texture.id != 0:
      rl.unload_texture(self._qr_texture)


class KoraniOnroadBadge:
  """Compact Korean deceleration pill rendered on top of the Mici road view."""

  def __init__(self):
    self._active_reader = CachedJsonFile(active_state_path)
    self._badge_enabled = True
    self._last_cfg_check = 0.0

  def _is_enabled(self, now: float) -> bool:
    if now - self._last_cfg_check >= 1.0:
      self._last_cfg_check = now
      try:
        self._badge_enabled = bool(load_config().get("onroad_badge", True))
      except Exception:
        self._badge_enabled = True
    return self._badge_enabled

  def render(self, content_rect: rl.Rectangle) -> None:
    now = time.monotonic()
    if not self._is_enabled(now):
      return

    data = self._active_reader.read()
    if not isinstance(data, dict) or not data.get("active"):
      return

    updated = data.get("updated_mono")
    if not isinstance(updated, (int, float)) or not (0.0 <= now - float(updated) <= 2.0):
      return

    label = str(data.get("label") or "").strip()
    if not label:
      return

    dist = data.get("distance_m")
    text = f"{label} · {int(round(float(dist)))}m" if isinstance(dist, (int, float)) else label

    font_size = 22.0
    measured = _measure_ko(text, font_size)
    pill_w = min(content_rect.width - 24.0, measured.x + 28.0)
    pill_h = 34.0
    pill_x = content_rect.x + (content_rect.width - pill_w) / 2.0
    pill_y = content_rect.y + 10.0

    kind = str(data.get("kind") or "")
    border = rl.Color(124, 231, 255, 230) if kind in ("camera", "section") else rl.Color(212, 237, 134, 235)
    bg = rl.Color(14, 20, 18, 215)
    rect = rl.Rectangle(pill_x, pill_y, pill_w, pill_h)
    rl.draw_rectangle_rounded(rect, 0.5, 10, bg)
    rl.draw_rectangle_rounded_lines_ex(rect, 0.5, 10, 2, border)

    text_x = pill_x + (pill_w - measured.x) / 2.0
    text_y = pill_y + (pill_h - measured.y) / 2.0
    _draw_ko(text, text_x, text_y, font_size, rl.WHITE)
