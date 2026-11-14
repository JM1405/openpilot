from __future__ import annotations

import math

from openpilot.sunnypilot.koranipilot.config import atomic_write_json, nav_state_path, save_config
from openpilot.sunnypilot.koranipilot.nav_controller import (
  DT_PLANNER,
  KPH_TO_MS,
  KoraniNavController,
  V_CRUISE_UNSET,
  dead_reckon,
)

ORIGIN_LAT = 37.5000
ORIGIN_LON = 127.0000


def _write_nav(seq: int, events: list[dict], active: bool = True, mock: bool = False, recv_mono: float = 100.0):
  atomic_write_json(nav_state_path(), {
    "seq": seq,
    "active": active,
    "mode": "free_drive",
    "received_mono": recv_mono,
    "received_wall": 1700000000.0,
    "gps": {
      "valid": True,
      "mock": mock,
      "lat": ORIGIN_LAT,
      "lon": ORIGIN_LON,
      "bearing_deg": 0.0,  # heading due north
      "speed_mps": 15.0,
      "accuracy_m": 4.0,
    },
    "events": events,
  })


def test_speed_bump_decel_and_smooth_release():
  save_config({"enabled": True, "bump_enabled": True, "bump_speed_kph": 25, "bump_lead_m": 12, "bump_comfort_decel": 1.1})
  ctrl = KoraniNavController()

  # Place bump 60m due north (bearing 0)
  b_lat, b_lon = dead_reckon(ORIGIN_LAT, ORIGIN_LON, 0.0, 60.0)
  _write_nav(1, [{
    "id": "KNSafetyCode_Hump:1",
    "kind": "bump",
    "lat": b_lat,
    "lon": b_lon,
    "bearing_deg": 0.0,
    "passed": False,
  }], recv_mono=100.0)

  v_cruise = 60.0 * KPH_TO_MS
  v_ego = 58.0 * KPH_TO_MS

  v_t, _ = ctrl.update(None, True, False, v_ego, 0.0, v_cruise, now_mono=100.1)
  expected_pass_mps = 25.0 * KPH_TO_MS
  # Effective decel distance = 60 - 1.5 (dead_reckon at 15*0.1) - 12 = 46.5m
  expected_env = math.sqrt(expected_pass_mps**2 + 2.0 * 1.1 * (60.0 - 1.5 - 12.0))
  assert abs(v_t - expected_env) < 0.25

  # Closer (10m away <= 12m lead buffer): holds bump_speed_kph smoothly
  b_close_lat, b_close_lon = dead_reckon(ORIGIN_LAT, ORIGIN_LON, 0.0, 10.0)
  _write_nav(2, [{
    "id": "KNSafetyCode_Hump:1",
    "kind": "bump",
    "lat": b_close_lat,
    "lon": b_close_lon,
    "bearing_deg": 0.0,
    "passed": False,
  }], recv_mono=100.2)
  v_hold, _ = ctrl.update(None, True, False, 10.0, 0.0, v_cruise, now_mono=100.2)
  assert abs(v_hold - expected_pass_mps) < 0.05

  # After passing bump: smoothly ramps up at <= 2.2 m/s^2 instead of instant jump to V_CRUISE_UNSET
  _write_nav(3, [{
    "id": "KNSafetyCode_Hump:1",
    "kind": "bump",
    "lat": b_close_lat,
    "lon": b_close_lon,
    "bearing_deg": 0.0,
    "passed": True,
  }], recv_mono=100.25)
  v_rel, _ = ctrl.update(None, True, False, expected_pass_mps, 0.0, v_cruise, now_mono=100.25)
  assert v_rel < v_cruise
  assert abs(v_rel - (expected_pass_mps + 2.2 * DT_PLANNER)) < 1e-4


def test_rejects_opposite_heading_and_parallel_road_bumps():
  ctrl = KoraniNavController()

  # Opposite direction bump (heading 180 vs ego 0)
  opp_lat, opp_lon = dead_reckon(ORIGIN_LAT, ORIGIN_LON, 0.0, 25.0)
  # Parallel road bump 25m to the east (> 15m cross-track threshold)
  side_lat, side_lon = dead_reckon(ORIGIN_LAT, ORIGIN_LON, 45.0, 35.0)

  _write_nav(1, [
    {"id": "opp", "kind": "bump", "lat": opp_lat, "lon": opp_lon, "bearing_deg": 180.0, "passed": False},
    {"id": "side", "kind": "bump", "lat": side_lat, "lon": side_lon, "bearing_deg": 0.0, "passed": False},
  ], recv_mono=100.0)

  v_t, _ = ctrl.update(None, True, False, 15.0, 0.0, 20.0, now_mono=100.05)
  assert v_t == V_CRUISE_UNSET


def test_sharp_turn_and_section_and_camera_offset():
  save_config({"sharp_turn_enabled": True, "sharp_turn_speed_kph": 40, "camera_enabled": True, "camera_offset_kph": 5})
  ctrl = KoraniNavController()

  turn_lat, turn_lon = dead_reckon(ORIGIN_LAT, ORIGIN_LON, 0.0, 20.0)
  _write_nav(1, [{
    "id": "turn1",
    "kind": "sharp_turn",
    "lat": turn_lat,
    "lon": turn_lon,
    "passed": False,
  }], recv_mono=100.0)
  v_turn, _ = ctrl.update(None, True, False, 18.0, 0.0, 22.0, now_mono=100.0)
  expected_turn = math.sqrt((40.0 * KPH_TO_MS) ** 2 + 2.0 * 1.0 * (20.0 - 15.0))
  assert abs(v_turn - expected_turn) < 0.05

  # Inside hold buffer (14m <= 15m): holds exact 40 km/h
  t_close_lat, t_close_lon = dead_reckon(ORIGIN_LAT, ORIGIN_LON, 0.0, 14.0)
  _write_nav(2, [{
    "id": "turn1",
    "kind": "sharp_turn",
    "lat": t_close_lat,
    "lon": t_close_lon,
    "passed": False,
  }], recv_mono=100.05)
  v_hold, _ = ctrl.update(None, True, False, 12.0, 0.0, 22.0, now_mono=100.05)
  assert abs(v_hold - (40.0 * KPH_TO_MS)) < 0.05

  # Clearing turn while section is active smoothly ramps speed upward instead of jumping
  _write_nav(3, [{
    "id": "sec1",
    "kind": "section",
    "limit_kph": 60,
    "in_section": True,
    "passed": False,
  }], recv_mono=100.1)
  v_ramp, _ = ctrl.update(None, True, False, 12.0, 0.0, 28.0, now_mono=100.1)
  assert abs(v_ramp - (40.0 * KPH_TO_MS + 2.2 * DT_PLANNER)) < 0.01

  # Fresh controller in active section enforcement: 60 km/h limit + 5 km/h offset = 65 km/h
  sec_ctrl = KoraniNavController()
  v_sec, _ = sec_ctrl.update(None, True, False, 25.0, 0.0, 28.0, now_mono=100.15)
  assert abs(v_sec - (65.0 * KPH_TO_MS)) < 0.05


def test_ttl_expiry_mock_gps_and_driver_override():
  ctrl = KoraniNavController()
  b_lat, b_lon = dead_reckon(ORIGIN_LAT, ORIGIN_LON, 0.0, 15.0)
  _write_nav(1, [{"id": "b1", "kind": "bump", "lat": b_lat, "lon": b_lon, "passed": False}], recv_mono=100.0)

  # Driver pressing gas (long_override=True) cancels immediately
  v_ov, _ = ctrl.update(None, True, True, 14.0, 0.0, 20.0, now_mono=100.1)
  assert v_ov == V_CRUISE_UNSET

  # TTL expiry > 3.5s returns V_CRUISE_UNSET
  v_exp, _ = ctrl.update(None, True, False, 14.0, 0.0, 20.0, now_mono=104.0)
  assert v_exp == V_CRUISE_UNSET

  # Mock GPS rejected
  _write_nav(2, [{"id": "b1", "kind": "bump", "lat": b_lat, "lon": b_lon, "passed": False}], mock=True, recv_mono=105.0)
  v_mock, _ = ctrl.update(None, True, False, 14.0, 0.0, 20.0, now_mono=105.1)
  assert v_mock == V_CRUISE_UNSET
