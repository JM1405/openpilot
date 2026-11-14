from __future__ import annotations

from openpilot.sunnypilot.koranipilot.catalog import apply_recommended_preset, read_all_settings, write_setting
from openpilot.sunnypilot.koranipilot.config import (
  CachedJsonFile,
  DEFAULT_CONFIG,
  atomic_write_json,
  load_config,
  nav_state_path,
  save_config,
)


def test_config_roundtrip_and_clamping():
  assert load_config() == DEFAULT_CONFIG
  saved = save_config({
    "bump_speed_kph": 999,
    "bump_lead_m": 1,
    "bump_comfort_decel": 5.0,
    "corner_vision_scale": 0.1,
    "camera_offset_kph": -99,
    "enabled": "false",
  })
  assert saved["bump_speed_kph"] == 45
  assert saved["bump_lead_m"] == 5
  assert saved["bump_comfort_decel"] == 2.0
  assert saved["corner_vision_scale"] == 0.85
  assert saved["camera_offset_kph"] == -10
  assert saved["enabled"] is False
  assert load_config() == saved


def test_cached_json_file_mtime_reload():
  path = nav_state_path()
  reader = CachedJsonFile(lambda: path)
  assert reader.read() is None

  atomic_write_json(path, {"seq": 1, "active": True})
  assert reader.read()["seq"] == 1

  atomic_write_json(path, {"seq": 2, "active": False})
  assert reader.read()["seq"] == 2


def test_catalog_read_write_strict_types_and_onroad_lock(fake_params):
  initial = read_all_settings(fake_params)
  assert len(initial["rows"]) == 74
  rows_by_key = {r["key"]: r for r in initial["rows"]}

  # Bool param write
  ok, _, val = write_setting(fake_params, "SmartCruiseControlVision", True, is_onroad=True)
  assert ok and val is True
  assert fake_params.get_bool("SmartCruiseControlVision") is True

  # Restart-gated param blocked onroad, allowed offroad
  restart_key = next(k for k, r in rows_by_key.items() if r["restart"])
  ok_on, msg_on, _ = write_setting(fake_params, restart_key, not rows_by_key[restart_key]["value"], is_onroad=True)
  assert ok_on is False
  assert "주행 중" in msg_on

  # Enum/Int/Float storage type verification via FakeParams strict type checker
  for r in initial["rows"]:
    if r["type"] == "enum" and r["options"]:
      non_null_opts = [o["value"] for o in r["options"] if o["value"] is not None]
      if non_null_opts:
        ok_enum, _, saved_v = write_setting(fake_params, r["key"], non_null_opts[-1], is_onroad=False)
        assert ok_enum, f"Failed writing enum key {r['key']}"
    elif r["storage"] in ("int", "float"):
      ok_num, _, _ = write_setting(fake_params, r["key"], r["min"] or 1, is_onroad=False)
      assert ok_num, f"Failed writing numeric key {r['key']}"


def test_apply_recommended_preset(fake_params):
  cfg = apply_recommended_preset(fake_params)
  assert fake_params.get_bool("SmartCruiseControlVision") is True
  assert fake_params.get_bool("SmartCruiseControlMap") is True
  assert cfg["bump_enabled"] is True
  assert cfg["bump_speed_kph"] == 25
  assert cfg["corner_vision_scale"] == 1.15
