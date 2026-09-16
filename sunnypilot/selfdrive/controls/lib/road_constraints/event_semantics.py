"""Public camera standard, revision 20 (2025-10), item 101.

Road up/down/both describes the ROAD ROUTE, not a compass heading or proven
enforcement direction. Coordinates describe installation, not a braking target.
"""
import math
import re

POLICY_VERSION = "camera-standard20-v2"


def code(value):
  text = str(value or "").strip()
  return str(int(text)) if re.fullmatch(r"[0-9]{1,2}", text) else None


def camera_semantics(row):
  raw = str(row.get("REGLT_SE", "")).strip()
  codes = {code(part) for part in raw.split("+")}
  direction = {"1": "roadUp", "2": "roadDown", "3": "roadBoth"}.get(code(row.get("ROAD_ROUTE_DRC")))
  position = str(row.get("REGLT_SCTN_LC_SE", "")).strip()
  section = {"1": "start", "2": "end"}.get(code(position)) if position else None
  length_raw = str(row.get("OVRSPD_REGLT_SCTN_LT", "")).strip()
  try:
    length_km = float(length_raw) if length_raw else None
  except ValueError:
    length_km = math.nan
  try:
    target = float(row.get("LMTT_VE", ""))
  except (TypeError, ValueError):
    target = math.nan
  status = "pointCandidate"
  if not codes or not codes <= {"1", "2", "3", "4", "99"}:
    status = "unknownEnforcement"
  elif "1" not in codes:
    status = "noSpeedEnforcement"
  elif not math.isfinite(target) or not 0 < target <= 130:
    status = "invalidSpeed"
  elif direction is None:
    status = "unknownRoadDirection"
  elif position or (length_km is not None and length_km != 0):
    # Never collapse a section start/end, malformed length, or missing pair into a point camera.
    status = "sectionNeedsPair" if section and (length_km is None or math.isfinite(length_km) and length_km >= 0) else "invalidSection"
  return {"policy": POLICY_VERSION, "status": status,
          "speed_enforcement_declared": codes <= {"1", "2", "3", "4", "99"} and "1" in codes,
          "road_direction": direction, "enforcement_bearing_deg": None, "section_endpoint": section,
          "section_length_m": length_km * 1000 if length_km is not None and math.isfinite(length_km) and length_km >= 0 else None,
          "coordinate_role": "installation", "binding_verified": False}
