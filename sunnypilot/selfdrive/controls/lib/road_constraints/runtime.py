"""Explicit development configuration; importing this module performs no I/O."""

import os


def enabled(environ=None):
  return (os.environ if environ is None else environ).get("KOREAN_ROAD_INPUT", "0") == "1"


def should_run(started, params, CP):
  # Runs offroad too so pairing/diagnostics survive ignition transitions.
  # No Params mutation or vehicle mode inference.
  return enabled()


def create_planner(CP, CP_SP):
  from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner
  from .observer import RoadObserver
  observer = RoadObserver() if enabled() else None
  try:
    return LongitudinalPlanner(CP, CP_SP, road_observer=observer), observer
  except Exception:
    if observer is not None:
      observer.close()
    raise
