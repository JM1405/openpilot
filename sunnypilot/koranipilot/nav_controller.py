"""Koranipilot 2.0 navigation, speed-bump, sharp-turn, and speed-camera decelerator.

Reads live companion frames written atomically by koranipilot_server and produces
smooth kinematic target speeds consumed by LongitudinalPlannerSP.
"""

from __future__ import annotations

import math
import time
from typing import Any

from openpilot.sunnypilot.koranipilot.config import (
  CachedJsonFile,
  active_state_path,
  atomic_write_json,
  load_config,
  nav_state_path,
)

try:
  from cereal import log as _cereal_log
  _LLK_VALID = _cereal_log.LiveLocationKalman.Status.valid
except Exception:  # pragma: no cover - stripped host unit test env
  _LLK_VALID = 1

EARTH_RADIUS_M = 6371008.8
KPH_TO_MS = 1.0 / 3.6
MS_TO_KPH = 3.6
V_CRUISE_UNSET = 255.0
MIN_TARGET_MPS = 5.0  # 18 km/h floor matching sunnypilot smart cruise control
NAV_TTL_SEC = 3.5
DT_PLANNER = 0.05  # 20 Hz planner loop
_RELEASE_ACCEL_MPS2 = 2.2
_ACTIVE_PUBLISH_INTERVAL = 0.25


def angle_delta(a_deg: float, b_deg: float) -> float:
  return abs((a_deg - b_deg + 180.0) % 360.0 - 180.0)


def tangent_xy(lon: float, lat: float, origin_lon: float, origin_lat: float) -> tuple[float, float]:
  dx = math.radians(lon - origin_lon) * EARTH_RADIUS_M * math.cos(math.radians(origin_lat))
  dy = math.radians(lat - origin_lat) * EARTH_RADIUS_M
  return dx, dy


def dead_reckon(lat: float, lon: float, bearing_deg: float, distance_m: float) -> tuple[float, float]:
  if distance_m <= 0.0:
    return lat, lon
  brg = math.radians(bearing_deg)
  d_north = distance_m * math.cos(brg)
  d_east = distance_m * math.sin(brg)
  new_lat = lat + math.degrees(d_north / EARTH_RADIUS_M)
  cos_lat = max(0.1, math.cos(math.radians(lat)))
  new_lon = lon + math.degrees(d_east / (EARTH_RADIUS_M * cos_lat))
  return new_lat, new_lon


def _is_valid_korea_wgs84(lat: Any, lon: Any) -> bool:
  try:
    la = float(lat)
    lo = float(lon)
  except (TypeError, ValueError):
    return False
  return math.isfinite(la) and math.isfinite(lo) and (32.5 <= la <= 39.5) and (124.0 <= lo <= 132.0)


def _finite_float(val: Any) -> float | None:
  if val is None or isinstance(val, bool):
    return None
  try:
    f = float(val)
    return f if math.isfinite(f) else None
  except (TypeError, ValueError):
    return None


def resolve_event_distance(
  ev: dict[str, Any],
  ego_lat: float | None,
  ego_lon: float | None,
  ego_bearing: float | None,
  v_ego: float,
  packet_age_s: float,
) -> float | None:
  """Returns signed forward distance in meters, or None if irrelevant/rejected."""
  if ev.get("passed") is True:
    return None

  kind = str(ev.get("kind") or "")
  ev_lat = _finite_float(ev.get("lat"))
  ev_lon = _finite_float(ev.get("lon"))
  ev_bearing = _finite_float(ev.get("bearing_deg"))
  fallback_dist = _finite_float(ev.get("distance_m"))

  if (
    ego_lat is not None
    and ego_lon is not None
    and _is_valid_korea_wgs84(ev_lat, ev_lon)
  ):
    dx, dy = tangent_xy(ev_lon, ev_lat, ego_lon, ego_lat)
    dist = math.hypot(dx, dy)

    if ego_bearing is not None and math.isfinite(ego_bearing):
      if ev_bearing is not None and angle_delta(ego_bearing, ev_bearing) > 60.0:
        return None
      if dist > 0.5:
        brg_to_ev = math.degrees(math.atan2(dx, dy)) % 360.0
        rel_deg = angle_delta(ego_bearing, brg_to_ev)
        rad = math.radians(rel_deg)
        d_along = dist * math.cos(rad)
        d_lat = abs(dist * math.sin(rad))
        if d_along < -4.0:
          return None
        if dist <= 45.0:
          max_lat = 15.0 if kind == "bump" else 22.0
          if d_lat > max_lat:
            return None
          return d_along
        if rel_deg > 42.0:
          return None
      return dist

    # Ego bearing not established (e.g. stationary): prefer explicit route distance if available.
    if fallback_dist is not None:
      adj = fallback_dist - max(0.0, v_ego) * max(0.0, packet_age_s)
      return None if adj < -4.0 else adj
    if ev.get("in_section"):
      return 0.0
    return None

  if fallback_dist is not None:
    adj = fallback_dist - max(0.0, v_ego) * max(0.0, packet_age_s)
    return None if adj < -4.0 else adj

  if kind == "section" and ev.get("in_section"):
    return 0.0

  return None


def _event_spec(ev: dict[str, Any], cfg: dict[str, Any], d_m: float) -> tuple[int, float, float, str] | None:
  """Returns (target_kph, hold_before_m, a_decel, label_ko) or None if filtered out."""
  kind = str(ev.get("kind") or "")
  if kind == "bump":
    if not cfg.get("bump_enabled", True) or d_m > 220.0:
      return None
    kph = int(cfg.get("bump_speed_kph", 25))
    return kph, float(cfg.get("bump_lead_m", 12)), float(cfg.get("bump_comfort_decel", 1.1)), f"방지턱 {kph}km/h"

  if kind == "sharp_turn":
    if not cfg.get("sharp_turn_enabled", True) or d_m > 300.0:
      return None
    kph = int(cfg.get("sharp_turn_speed_kph", 40))
    return kph, 15.0, 1.0, f"급커브 {kph}km/h"

  if kind in ("camera", "section"):
    if not cfg.get("camera_enabled", True):
      return None
    in_section = (kind == "section") and bool(ev.get("in_section"))
    if not in_section and d_m > 600.0:
      return None
    limit = _finite_float(ev.get("limit_kph"))
    if limit is None or not (20.0 <= limit <= 140.0):
      return None
    kph = max(20, int(round(limit + int(cfg.get("camera_offset_kph", 0)))))
    title = "구간단속" if kind == "section" else "과속단속"
    return kph, 25.0, 1.0, f"{title} {kph}km/h"

  return None


def evaluate_candidates(
  events: list[dict[str, Any]],
  cfg: dict[str, Any],
  ego_lat: float | None,
  ego_lon: float | None,
  ego_bearing: float | None,
  v_ego: float,
  v_cruise: float,
  packet_age_s: float,
) -> tuple[float, dict[str, Any] | None]:
  """Evaluates all upcoming events and returns (min_v_target_mps, winning_info)."""
  best_v = V_CRUISE_UNSET
  best_info: dict[str, Any] | None = None

  for ev in events:
    if not isinstance(ev, dict):
      continue
    d_m = resolve_event_distance(ev, ego_lat, ego_lon, ego_bearing, v_ego, packet_age_s)
    if d_m is None:
      continue
    spec = _event_spec(ev, cfg, d_m)
    if spec is None:
      continue

    target_kph, d_hold, a_decel, label_ko = spec
    v_pass = max(MIN_TARGET_MPS, target_kph * KPH_TO_MS)
    if v_pass >= v_cruise:
      continue

    in_section = (ev.get("kind") == "section") and bool(ev.get("in_section"))
    eff_dist = 0.0 if in_section else max(0.0, d_m - d_hold)
    v_env = math.sqrt(v_pass * v_pass + 2.0 * a_decel * eff_dist)

    if in_section or v_env < (v_ego + 1.5) or d_m <= (d_hold + 35.0):
      cand_v = max(v_pass, min(v_cruise, v_env))
      if cand_v < best_v:
        best_v = cand_v
        best_info = {
          "active": True,
          "kind": str(ev.get("kind") or ""),
          "label": label_ko,
          "distance_m": None if in_section else round(max(0.0, d_m), 1),
          "target_kph": target_kph,
        }

  return best_v, best_info


class KoraniNavController:
  """Stateful 20 Hz longitudinal target arbitrator for bumps, sharp turns, and cameras."""

  def __init__(self):
    self._nav_reader = CachedJsonFile(nav_state_path)
    self._prev_v_target: float | None = None
    self._last_active_sig: tuple[bool, str, str] = (False, "", "")
    self._last_publish_mono: float = 0.0

  def _extract_ego(
    self,
    sm: Any,
    packet: dict[str, Any],
    v_ego: float,
    packet_age_s: float,
  ) -> tuple[float | None, float | None, float | None]:
    if sm is not None:
      try:
        loc = sm["liveLocationKalman"]
        if loc.status == _LLK_VALID and loc.positionGeodetic.valid and len(loc.positionGeodetic.value) >= 2:
          lat = float(loc.positionGeodetic.value[0])
          lon = float(loc.positionGeodetic.value[1])
          bearing = None
          if len(loc.calibratedOrientationNED.value) >= 3:
            bearing = math.degrees(float(loc.calibratedOrientationNED.value[2])) % 360.0
          if _is_valid_korea_wgs84(lat, lon) or (math.isfinite(lat) and math.isfinite(lon) and abs(lat) > 1.0):
            return lat, lon, bearing
      except Exception:
        pass

    gps = packet.get("gps")
    if isinstance(gps, dict) and gps.get("valid") and not gps.get("mock"):
      lat = _finite_float(gps.get("lat"))
      lon = _finite_float(gps.get("lon"))
      bearing = _finite_float(gps.get("bearing_deg"))
      if lat is not None and lon is not None:
        if bearing is not None and v_ego > 0.5 and packet_age_s > 0.0:
          lat, lon = dead_reckon(lat, lon, bearing, v_ego * packet_age_s)
        return lat, lon, bearing

    return None, None, None

  def _publish_active_state(self, state: dict[str, Any], now_mono: float) -> None:
    sig = (bool(state.get("active")), str(state.get("kind", "")), str(state.get("label", "")))
    if sig != self._last_active_sig or (now_mono - self._last_publish_mono) >= _ACTIVE_PUBLISH_INTERVAL:
      payload = {
        "active": bool(state.get("active")),
        "kind": str(state.get("kind", "")),
        "label": str(state.get("label", "")),
        "distance_m": state.get("distance_m"),
        "target_kph": state.get("target_kph"),
        "updated_mono": round(now_mono, 3),
      }
      try:
        atomic_write_json(active_state_path(), payload, sync_disk=False)
      except OSError:
        pass
      self._last_active_sig = sig
      self._last_publish_mono = now_mono

  def _reset_and_return(self, a_ego: float, now_mono: float) -> tuple[float, float]:
    self._prev_v_target = None
    self._publish_active_state({"active": False, "kind": "", "label": "", "distance_m": None, "target_kph": None}, now_mono)
    return V_CRUISE_UNSET, a_ego

  def update(
    self,
    sm: Any,
    long_enabled: bool,
    long_override: bool,
    v_ego: float,
    a_ego: float,
    v_cruise: float,
    now_mono: float | None = None,
  ) -> tuple[float, float]:
    now = time.monotonic() if now_mono is None else float(now_mono)
    cfg = load_config()

    if not cfg.get("enabled", True) or not long_enabled or long_override:
      return self._reset_and_return(a_ego, now)

    packet = self._nav_reader.read()
    if not isinstance(packet, dict) or not packet.get("active"):
      return self._reset_and_return(a_ego, now)

    recv_mono = _finite_float(packet.get("received_mono"))
    if recv_mono is None:
      return self._reset_and_return(a_ego, now)

    packet_age = now - recv_mono
    if packet_age < -0.5 or packet_age > NAV_TTL_SEC:
      return self._reset_and_return(a_ego, now)

    ego_lat, ego_lon, ego_bearing = self._extract_ego(sm, packet, v_ego, max(0.0, packet_age))
    events = packet.get("events") if isinstance(packet.get("events"), list) else []

    desired_v, info = evaluate_candidates(
      events=events,
      cfg=cfg,
      ego_lat=ego_lat,
      ego_lon=ego_lon,
      ego_bearing=ego_bearing,
      v_ego=v_ego,
      v_cruise=v_cruise,
      packet_age_s=max(0.0, packet_age),
    )

    if desired_v < V_CRUISE_UNSET:
      if self._prev_v_target is not None and desired_v > self._prev_v_target:
        desired_v = min(desired_v, self._prev_v_target + _RELEASE_ACCEL_MPS2 * DT_PLANNER)
      self._prev_v_target = desired_v
      assert info is not None
      self._publish_active_state(info, now)
      return desired_v, a_ego

    if self._prev_v_target is not None:
      ramped = self._prev_v_target + _RELEASE_ACCEL_MPS2 * DT_PLANNER
      if ramped < (v_cruise - 0.1):
        self._prev_v_target = ramped
        self._publish_active_state({"active": False, "kind": "", "label": "", "distance_m": None, "target_kph": None}, now)
        return ramped, a_ego

    return self._reset_and_return(a_ego, now)
