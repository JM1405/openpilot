"""Configuration and atomic IPC state helpers for Koranipilot 2.0.

All persistent Koranipilot settings live in JSON under /data/koranipilot/config.json
so precompiled common/params_keys.h and common/params_pyx.so never need changes.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from typing import Any

try:
  from openpilot.system.hardware.hw import Paths
except Exception:  # pragma: no cover - fallback for stripped test envs
  Paths = None

DEFAULT_CONFIG: dict[str, Any] = {
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
}

_BOOL_KEYS = ("enabled", "bump_enabled", "sharp_turn_enabled", "camera_enabled", "onroad_badge")
_INT_BOUNDS: dict[str, tuple[int, int]] = {
  "bump_speed_kph": (15, 45),
  "bump_lead_m": (5, 25),
  "sharp_turn_speed_kph": (20, 75),
  "camera_offset_kph": (-10, 15),
}
_FLOAT_BOUNDS: dict[str, tuple[float, float]] = {
  "bump_comfort_decel": (0.6, 2.0),
  "corner_vision_scale": (0.85, 1.45),
}


def korani_dir() -> str:
  override = os.environ.get("KORANIPILOT_DIR")
  if override:
    return override
  if os.path.isdir("/data") and os.access("/data", os.W_OK):
    return "/data/koranipilot"
  if Paths is not None:
    return os.path.join(Paths.comma_home(), "koranipilot")
  return os.path.join(os.path.expanduser("~"), ".comma", "koranipilot")


def shm_dir() -> str:
  override = os.environ.get("KORANIPILOT_SHM_DIR")
  if override:
    return override
  if os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK):
    return "/dev/shm"
  return korani_dir()


def config_path() -> str:
  return os.path.join(korani_dir(), "config.json")


def nav_state_path() -> str:
  return os.path.join(shm_dir(), "koranipilot_nav.json")


def active_state_path() -> str:
  return os.path.join(shm_dir(), "koranipilot_active.json")


def sanitize_config(raw: dict[str, Any] | None) -> dict[str, Any]:
  merged = copy.deepcopy(DEFAULT_CONFIG)
  if not isinstance(raw, dict):
    return merged

  for key in _BOOL_KEYS:
    if key in raw:
      val = raw[key]
      if isinstance(val, str):
        merged[key] = val.strip().lower() in ("1", "true", "yes", "on")
      else:
        merged[key] = bool(val)

  for key, (lo, hi) in _INT_BOUNDS.items():
    if key in raw:
      try:
        merged[key] = max(lo, min(hi, int(round(float(raw[key])))))
      except (TypeError, ValueError):
        pass

  for key, (lo, hi) in _FLOAT_BOUNDS.items():
    if key in raw:
      try:
        val = float(raw[key])
        if val == val:  # reject NaN
          merged[key] = round(max(lo, min(hi, val)), 2)
      except (TypeError, ValueError):
        pass

  return merged


def atomic_write_json(path: str, payload: dict[str, Any], sync_disk: bool = False) -> None:
  parent = os.path.dirname(os.path.abspath(path))
  os.makedirs(parent, exist_ok=True)
  fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=parent)
  try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
      json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
      if sync_disk:
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
  except Exception:
    try:
      os.unlink(tmp_path)
    except OSError:
      pass
    raise


class CachedJsonFile:
  """Reads JSON only when file size or mtime changes."""

  def __init__(self, path_fn):
    self._path_fn = path_fn
    self._cached_path: str | None = None
    self._cached_sig: tuple[int, int] | None = None
    self._cached_data: dict[str, Any] | None = None

  def read(self) -> dict[str, Any] | None:
    path = self._path_fn()
    try:
      st = os.stat(path)
      sig = (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
      self._cached_sig = None
      self._cached_data = None
      return None

    if path == self._cached_path and sig == self._cached_sig:
      return self._cached_data

    try:
      with open(path, encoding="utf-8") as f:
        data = json.load(f)
    except (OSError, ValueError):
      return None

    if not isinstance(data, dict):
      return None

    self._cached_path = path
    self._cached_sig = sig
    self._cached_data = data
    return data


_config_reader = CachedJsonFile(config_path)


def load_config() -> dict[str, Any]:
  raw = _config_reader.read()
  return sanitize_config(raw)


def save_config(patch: dict[str, Any]) -> dict[str, Any]:
  current = load_config()
  if isinstance(patch, dict):
    current.update(patch)
  cleaned = sanitize_config(current)
  atomic_write_json(config_path(), cleaned, sync_disk=True)
  return cleaned
