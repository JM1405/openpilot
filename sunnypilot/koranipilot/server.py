"""Lightweight C4 HTTP web remote, UDP beacon, and phone nav receiver (port 7000)."""

from __future__ import annotations

import json
import math
import socket
import threading
import time
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from openpilot.sunnypilot.koranipilot import DEFAULT_UDP_BEACON_PORT, DEFAULT_WEB_PORT, VERSION
from openpilot.sunnypilot.koranipilot.catalog import apply_recommended_preset, read_all_settings, write_setting
from openpilot.sunnypilot.koranipilot.config import (
  CachedJsonFile,
  active_state_path,
  atomic_write_json,
  load_config,
  nav_state_path,
  save_config,
)
from openpilot.sunnypilot.koranipilot.nav_controller import NAV_TTL_SEC
from openpilot.sunnypilot.koranipilot.net import get_broadcast_addresses, get_lan_ip
from openpilot.sunnypilot.koranipilot.web_ui import WEB_HTML

try:
  from openpilot.common.params import Params
except Exception:  # pragma: no cover - test/non-Linux fallback
  Params = None

MODEL_INDEX_URL = "https://raw.githubusercontent.com/sunnypilot/sunnypilot-models/refs/heads/gh-pages/docs/driving_models_v17.json"
REQUIRED_MODEL_SELECTOR_VERSION = 15
_ALLOWED_KINDS = ("bump", "sharp_turn", "camera", "section", "other")
_MAX_EVENTS = 16


def _finite(val: Any) -> float | None:
  if val is None or isinstance(val, bool):
    return None
  try:
    num = float(val)
    return num if math.isfinite(num) else None
  except (TypeError, ValueError):
    return None


def sanitize_nav_packet(raw: dict[str, Any], recv_mono: float, recv_wall: float) -> dict[str, Any]:
  gps_raw = raw.get("gps") if isinstance(raw.get("gps"), dict) else {}
  gps = {
    "valid": bool(gps_raw.get("valid", False)),
    "lat": _finite(gps_raw.get("lat")),
    "lon": _finite(gps_raw.get("lon")),
    "speed_mps": _finite(gps_raw.get("speed_mps")),
    "bearing_deg": _finite(gps_raw.get("bearing_deg")),
    "accuracy_m": _finite(gps_raw.get("accuracy_m")),
    "mock": bool(gps_raw.get("mock", False)),
  }

  events: list[dict[str, Any]] = []
  raw_events = raw.get("events") if isinstance(raw.get("events"), list) else []
  for idx, item in enumerate(raw_events):
    if len(events) >= _MAX_EVENTS or not isinstance(item, dict):
      break
    kind = str(item.get("kind") or "other")
    if kind not in _ALLOWED_KINDS:
      kind = "other"
    limit_num = _finite(item.get("limit_kph"))
    limit_kph = int(round(limit_num)) if (limit_num is not None and 1 <= limit_num <= 160) else None
    events.append({
      "id": str(item.get("id") or f"{kind}:{idx}")[:64],
      "kind": kind,
      "lat": _finite(item.get("lat")),
      "lon": _finite(item.get("lon")),
      "bearing_deg": _finite(item.get("bearing_deg")),
      "distance_m": _finite(item.get("distance_m")),
      "limit_kph": limit_kph,
      "passed": bool(item.get("passed", False)),
      "in_section": bool(item.get("in_section", False)),
    })

  seq = 0
  try:
    seq = int(raw.get("seq", 0))
  except (TypeError, ValueError):
    seq = 0

  mode = "route" if raw.get("mode") == "route" else "free_drive"
  return {
    "seq": seq,
    "active": bool(raw.get("active", False)),
    "mode": mode,
    "received_mono": round(recv_mono, 3),
    "received_wall": round(recv_wall, 3),
    "gps": gps,
    "events": events,
  }


def summarize_nav(packet: dict[str, Any] | None, now_mono: float) -> dict[str, Any]:
  if not isinstance(packet, dict) or not packet.get("active"):
    return {"connected": False, "fresh": False, "mode": "idle", "gps_ok": False, "counts": {}, "age_ms": None}
  recv = _finite(packet.get("received_mono"))
  age_s = (now_mono - recv) if recv is not None else 999.0
  fresh = 0.0 <= age_s <= NAV_TTL_SEC
  counts = {"bump": 0, "sharp_turn": 0, "camera": 0, "section": 0}
  for ev in packet.get("events", []):
    k = ev.get("kind")
    if k in counts and not ev.get("passed"):
      counts[k] += 1
  gps = packet.get("gps") or {}
  return {
    "connected": True,
    "fresh": fresh,
    "mode": packet.get("mode", "free_drive"),
    "gps_ok": bool(gps.get("valid") and not gps.get("mock")),
    "counts": counts,
    "age_ms": max(0, int(round(age_s * 1000))) if recv is not None else None,
  }


def _parse_models_state(params: Any) -> dict[str, Any]:
  active_raw = params.get("ModelManager_ActiveBundle") or {}
  active_name = None
  active_index = None
  if isinstance(active_raw, dict) and active_raw:
    active_name = active_raw.get("displayName") or active_raw.get("display_name") or active_raw.get("internalName")
    active_index = active_raw.get("index")

  downloading = params.get("ModelManager_DownloadIndex")
  cache = params.get("ModelManager_ModelsCache") or {}
  raw_bundles = cache.get("bundles", []) if isinstance(cache, dict) else []

  bundles = []
  for b in raw_bundles:
    if not isinstance(b, dict):
      continue
    sel_ver = b.get("minimum_selector_version", b.get("minimumSelectorVersion", 0))
    try:
      if int(sel_ver) != REQUIRED_MODEL_SELECTOR_VERSION:
        continue
    except (TypeError, ValueError):
      continue
    overrides = b.get("overrides") or {}
    folder = overrides.get("folder", "") if isinstance(overrides, dict) else ""
    bundles.append({
      "index": int(b.get("index", -1)),
      "display_name": str(b.get("display_name") or b.get("displayName") or b.get("short_name") or ""),
      "short_name": str(b.get("short_name") or b.get("internalName") or ""),
      "generation": int(b.get("generation", 0)),
      "folder": folder,
    })

  bundles.sort(key=lambda item: item["index"], reverse=True)
  return {
    "active_name": active_name,
    "active_index": active_index,
    "downloading_index": downloading,
    "bundles": bundles,
  }


class KoraniBackend:
  """Testable application core backing HTTP endpoints."""

  def __init__(self, params: Any, port: int = DEFAULT_WEB_PORT):
    self.params = params
    self.port = port
    self._nav_reader = CachedJsonFile(nav_state_path)
    self._active_reader = CachedJsonFile(active_state_path)

  def _is_onroad(self) -> bool:
    try:
      return bool(self.params.get_bool("IsOnroad"))
    except Exception:
      return False

  def _read_active_decel(self) -> dict[str, Any]:
    data = self._active_reader.read()
    if not isinstance(data, dict):
      return {"active": False, "kind": "", "label": "", "distance_m": None, "target_kph": None}
    updated = _finite(data.get("updated_mono"))
    if updated is None or (time.monotonic() - updated) > 2.0:
      return {"active": False, "kind": "", "label": "", "distance_m": None, "target_kph": None}
    return data

  def get_status(self) -> dict[str, Any]:
    now = time.monotonic()
    quick = {}
    for key in ("SmartCruiseControlVision", "SmartCruiseControlMap", "AlphaLongitudinalEnabled", "CustomAccIncrementsEnabled"):
      try:
        quick[key] = bool(self.params.get_bool(key))
      except Exception:
        quick[key] = False

    return {
      "service": "koranipilot",
      "version": VERSION,
      "port": self.port,
      "lan_ip": get_lan_ip(),
      "is_onroad": self._is_onroad(),
      "config": load_config(),
      "active_decel": self._read_active_decel(),
      "nav_summary": summarize_nav(self._nav_reader.read(), now),
      "quick_toggles": quick,
    }

  def post_korani_config(self, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("action") == "recommended":
      cfg = apply_recommended_preset(self.params)
      return {"ok": True, "config": cfg, "message": "방지턱 · 코너 · 단속 추천 세팅을 켰어요!"}
    cfg = save_config(payload)
    return {"ok": True, "config": cfg, "message": "설정을 저장했어요."}

  def get_settings(self) -> dict[str, Any]:
    return read_all_settings(self.params)

  def post_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
    key = str(payload.get("key") or "")
    ok, msg, val = write_setting(self.params, key, payload.get("value"), is_onroad=self._is_onroad())
    return {"ok": ok, "key": key, "value": val, "message": msg}

  def get_models(self) -> dict[str, Any]:
    state = _parse_models_state(self.params)
    state["is_onroad"] = self._is_onroad()
    return state

  def post_models(self, payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "")
    onroad = self._is_onroad()
    if action == "refresh":
      try:
        req = urllib.request.Request(MODEL_INDEX_URL, headers={"User-Agent": "Koranipilot/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
          data = json.loads(resp.read().decode("utf-8"))
        self.params.put("ModelManager_ModelsCache", data, block=True)
        self.params.put("ModelManager_LastSyncTime", int(time.monotonic() * 1e9), block=True)
        return {"ok": True, "message": "최신 모델 목록을 가져왔어요."}
      except Exception as exc:
        return {"ok": False, "message": f"목록을 못 가져왔어요 (인터넷 연결 확인): {exc}"}

    if onroad:
      return {"ok": False, "message": "주행 중엔 모델을 바꿀 수 없어요. 정차 중에 해주세요."}

    if action == "select":
      try:
        idx = int(payload.get("index"))
      except (TypeError, ValueError):
        return {"ok": False, "message": "잘못된 모델 번호예요."}
      self.params.put("ModelManager_DownloadIndex", idx, block=True)
      return {"ok": True, "message": "모델 다운로드를 시작했어요."}

    if action == "reset_stock":
      self.params.remove("ModelManager_ActiveBundle")
      self.params.remove("ModelManager_DownloadIndex")
      return {"ok": True, "message": "순정 기본 모델로 되돌렸어요."}

    return {"ok": False, "message": "알 수 없는 요청이에요."}

  def post_reboot(self) -> dict[str, Any]:
    if self._is_onroad():
      return {"ok": False, "message": "주행 중에는 재부팅할 수 없어요."}
    self.params.put_bool("DoReboot", True, block=True)
    return {"ok": True, "message": "잠시 뒤 콤마4가 재부팅돼요."}

  def post_nav(self, payload: dict[str, Any]) -> dict[str, Any]:
    snap = sanitize_nav_packet(payload, recv_mono=time.monotonic(), recv_wall=time.time())
    atomic_write_json(nav_state_path(), snap, sync_disk=False)
    return {
      "ok": True,
      "seq": snap["seq"],
      "active_decel": self._read_active_decel(),
    }


def _make_handler(backend: KoraniBackend):
  class KoraniRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
      return

    def _send_bytes(self, status: int, content_type: str, data: bytes) -> None:
      self.send_response(status)
      self.send_header("Content-Type", content_type)
      self.send_header("Content-Length", str(len(data)))
      self.send_header("Cache-Control", "no-store")
      self.end_headers()
      self.wfile.write(data)

    def _send_json(self, status: int, payload: Any) -> None:
      body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
      self._send_bytes(status, "application/json; charset=utf-8", body)

    def _read_json_body(self) -> dict[str, Any] | None:
      try:
        length = int(self.headers.get("Content-Length", "0"))
      except ValueError:
        return None
      if length <= 0 or length > 262144:
        return {}
      raw = self.rfile.read(length)
      try:
        obj = json.loads(raw.decode("utf-8"))
        return obj if isinstance(obj, dict) else None
      except ValueError:
        return None

    def do_GET(self) -> None:  # noqa: N802
      path = self.path.split("?", 1)[0]
      if path in ("/", "/index.html"):
        self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", WEB_HTML.encode("utf-8"))
      elif path == "/api/status":
        self._send_json(HTTPStatus.OK, backend.get_status())
      elif path == "/api/settings":
        self._send_json(HTTPStatus.OK, backend.get_settings())
      elif path == "/api/models":
        self._send_json(HTTPStatus.OK, backend.get_models())
      else:
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
      path = self.path.split("?", 1)[0]
      body = self._read_json_body()
      if body is None:
        self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": "잘못된 요청 형식이에요."})
        return

      if path == "/api/nav":
        self._send_json(HTTPStatus.OK, backend.post_nav(body))
      elif path == "/api/korani-config":
        self._send_json(HTTPStatus.OK, backend.post_korani_config(body))
      elif path == "/api/settings":
        self._send_json(HTTPStatus.OK, backend.post_settings(body))
      elif path == "/api/models":
        self._send_json(HTTPStatus.OK, backend.post_models(body))
      elif path == "/api/reboot":
        self._send_json(HTTPStatus.OK, backend.post_reboot())
      else:
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "not_found"})

  return KoraniRequestHandler


class KoraniServer:
  """Runs the HTTP server and optional UDP auto-discovery beacon."""

  def __init__(
    self,
    params: Any = None,
    port: int = DEFAULT_WEB_PORT,
    enable_beacon: bool = True,
    beacon_port: int = DEFAULT_UDP_BEACON_PORT,
  ):
    if params is None:
      if Params is None:
        raise RuntimeError("Params is unavailable on this platform")
      params = Params()
    self.backend = KoraniBackend(params=params, port=port)
    self._httpd = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(self.backend))
    self._httpd.daemon_threads = True
    self.port = int(self._httpd.server_address[1])
    self.backend.port = self.port
    self._enable_beacon = enable_beacon
    self._beacon_port = beacon_port
    self._stop_event = threading.Event()
    self._http_thread: threading.Thread | None = None
    self._beacon_thread: threading.Thread | None = None

  def _beacon_loop(self) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    cached_ip: str | None = None
    last_ip_check = 0.0
    try:
      while not self._stop_event.is_set():
        now = time.monotonic()
        if now - last_ip_check >= 5.0:
          cached_ip = get_lan_ip()
          last_ip_check = now
        if cached_ip:
          packet = json.dumps({
            "service": "koranipilot",
            "version": 2,
            "ip": cached_ip,
            "port": self.port,
            "device": "comma-four",
          }).encode("utf-8")
          for target in get_broadcast_addresses(cached_ip):
            try:
              sock.sendto(packet, (target, self._beacon_port))
            except OSError:
              pass
        self._stop_event.wait(1.0)
    finally:
      sock.close()

  def start(self) -> None:
    self._http_thread = threading.Thread(target=self._httpd.serve_forever, name="korani-http", daemon=True)
    self._http_thread.start()
    if self._enable_beacon:
      self._beacon_thread = threading.Thread(target=self._beacon_loop, name="korani-beacon", daemon=True)
      self._beacon_thread.start()

  def stop(self) -> None:
    self._stop_event.set()
    self._httpd.shutdown()
    self._httpd.server_close()
    if self._http_thread:
      self._http_thread.join(timeout=2.0)
    if self._beacon_thread:
      self._beacon_thread.join(timeout=2.0)


def main() -> None:
  import os
  port = int(os.environ.get("KORANIPILOT_PORT", str(DEFAULT_WEB_PORT)))
  srv = KoraniServer(port=port, enable_beacon=True)
  srv.start()
  try:
    while True:
      time.sleep(60.0)
  except KeyboardInterrupt:
    pass
  finally:
    srv.stop()


if __name__ == "__main__":
  main()
