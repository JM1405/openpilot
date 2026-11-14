"""74-item Korean sunnypilot settings catalog reader/writer over stock Params."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from openpilot.sunnypilot.koranipilot.config import save_config

_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "settings_catalog.json")


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
  with open(_CATALOG_PATH, encoding="utf-8") as f:
    return json.load(f)


def _row_by_key() -> dict[str, dict[str, Any]]:
  return {row["key"]: row for row in load_catalog().get("rows", []) if "key" in row}


def _allows_none(row: dict[str, Any]) -> bool:
  return any(opt.get("value") is None for opt in (row.get("options") or []))


def _read_row_value(params: Any, row: dict[str, Any]) -> Any:
  key = row["key"]
  storage = row.get("storage", "bool")
  try:
    if storage == "bool":
      return bool(params.get_bool(key))
    use_default = not _allows_none(row)
    val = params.get(key, return_default=use_default)
    if val is None:
      return None
    if storage == "int":
      return int(val)
    if storage == "float":
      return round(float(val), 4)
    return val
  except Exception:
    return row.get("default")


def read_all_settings(params: Any) -> dict[str, Any]:
  cat = load_catalog()
  groups = cat.get("groups", [])
  rows_out = []
  for row in cat.get("rows", []):
    rows_out.append({
      "key": row["key"],
      "group": row.get("group", "driving"),
      "title": row.get("title", row["key"]),
      "type": row.get("type", "bool"),
      "storage": row.get("storage", "bool"),
      "restart": bool(row.get("restart", False)),
      "options": row.get("options") or [],
      "min": row.get("min"),
      "max": row.get("max"),
      "step": row.get("step"),
      "value": _read_row_value(params, row),
    })
  return {"groups": groups, "rows": rows_out}


def write_setting(params: Any, key: str, value: Any, is_onroad: bool = False) -> tuple[bool, str, Any]:
  row = _row_by_key().get(key)
  if row is None:
    return False, f"알 수 없는 설정 항목이에요: {key}", None

  if is_onroad and row.get("restart"):
    return False, "이 설정은 주행 중엔 바꿀 수 없어요. 정차 중에 바꿔주세요.", _read_row_value(params, row)

  storage = row.get("storage", "bool")
  options = row.get("options") or []

  if value is None:
    if _allows_none(row):
      params.remove(key)
      return True, "기본값으로 되돌렸어요.", None
    return False, "이 항목은 비울 수 없어요.", _read_row_value(params, row)

  try:
    if storage == "bool":
      if isinstance(value, str):
        casted: Any = value.strip().lower() in ("1", "true", "yes", "on")
      else:
        casted = bool(value)
      params.put_bool(key, casted, block=True)
      return True, "저장했어요.", _read_row_value(params, row)

    if storage == "int":
      num = float(value)
      if num != num:
        raise ValueError("NaN")
      casted = int(round(num))
      if options:
        allowed = {int(o["value"]) for o in options if o.get("value") is not None}
        if casted not in allowed:
          return False, "허용되지 않는 선택값이에요.", _read_row_value(params, row)
      if row.get("min") is not None:
        casted = max(int(row["min"]), casted)
      if row.get("max") is not None:
        casted = min(int(row["max"]), casted)
      params.put(key, casted, block=True)
      return True, "저장했어요.", _read_row_value(params, row)

    if storage == "float":
      casted = float(value)
      if casted != casted:
        raise ValueError("NaN")
      if options:
        allowed_f = {float(o["value"]) for o in options if o.get("value") is not None}
        if casted not in allowed_f:
          return False, "허용되지 않는 선택값이에요.", _read_row_value(params, row)
      if row.get("min") is not None:
        casted = max(float(row["min"]), casted)
      if row.get("max") is not None:
        casted = min(float(row["max"]), casted)
      params.put(key, float(casted), block=True)
      return True, "저장했어요.", _read_row_value(params, row)

    params.put(key, str(value), block=True)
    return True, "저장했어요.", _read_row_value(params, row)
  except (TypeError, ValueError) as exc:
    return False, f"잘못된 값 형식이에요: {exc}", _read_row_value(params, row)


def apply_recommended_preset(params: Any) -> dict[str, Any]:
  """Enables SCC-V, SCC-M, and balanced bump/corner/camera defaults in one tap."""
  params.put_bool("SmartCruiseControlVision", True, block=True)
  params.put_bool("SmartCruiseControlMap", True, block=True)
  return save_config({
    "enabled": True,
    "bump_enabled": True,
    "bump_speed_kph": 25,
    "bump_lead_m": 12,
    "bump_comfort_decel": 1.1,
    "corner_vision_scale": 1.15,
    "sharp_turn_enabled": True,
    "sharp_turn_speed_kph": 40,
    "camera_enabled": True,
    "camera_offset_kph": 0,
    "onroad_badge": True,
  })
