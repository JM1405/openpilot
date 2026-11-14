from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
PARAMS_KEYS_H = REPO_ROOT / "common" / "params_keys.h"


def parse_params_keys_h() -> dict[str, str]:
  """Parses common/params_keys.h into {key_name: PARAM_TYPE}."""
  text = PARAMS_KEYS_H.read_text(encoding="utf-8")
  pattern = re.compile(r'\{\s*"([A-Za-z0-9_]+)"\s*,\s*\{[^}]*?,\s*([A-Z]+)(?:,|\s*\})')
  keys = {match.group(1): match.group(2) for match in pattern.finditer(text)}
  assert len(keys) >= 200, f"Unexpectedly few parsed keys from {PARAMS_KEYS_H}: {len(keys)}"
  return keys


class UnknownKeyName(Exception):
  pass


class FakeParams:
  """Strict test double matching common/params_pyx.pyx exact type & key rules."""

  def __init__(self, initial: dict[str, Any] | None = None):
    self._schema = parse_params_keys_h()
    self._store: dict[str, Any] = {}
    if initial:
      for k, v in initial.items():
        self.put(k, v)

  def _require_key(self, key: str) -> str:
    if key not in self._schema:
      raise UnknownKeyName(key)
    return self._schema[key]

  def put(self, key: str, dat: Any, block: bool = False) -> None:
    ptype = self._require_key(key)
    if ptype == "BOOL":
      if type(dat) is not bool:
        raise TypeError(f"{key} expects bool, got {type(dat)}")
    elif ptype in ("INT", "TIME"):
      if type(dat) is not int:
        raise TypeError(f"{key} expects int, got {type(dat)}")
    elif ptype == "FLOAT":
      if type(dat) is not float:
        raise TypeError(f"{key} expects float, got {type(dat)}")
    elif ptype == "JSON":
      if type(dat) is not dict:
        raise TypeError(f"{key} expects dict, got {type(dat)}")
    elif ptype in ("STRING", "BYTES"):
      if not isinstance(dat, (str, bytes)):
        raise TypeError(f"{key} expects str/bytes, got {type(dat)}")
    self._store[key] = dat

  def put_bool(self, key: str, val: bool, block: bool = False) -> None:
    self.put(key, bool(val), block=block)

  def get(self, key: str, block: bool = False, return_default: bool = False) -> Any:
    ptype = self._require_key(key)
    if key in self._store:
      return self._store[key]
    if return_default:
      return {
        "BOOL": False,
        "INT": 0,
        "FLOAT": 0.0,
        "TIME": 0,
        "STRING": "",
        "JSON": {},
        "BYTES": b"",
      }.get(ptype)
    return None

  def get_bool(self, key: str, block: bool = False) -> bool:
    self._require_key(key)
    return bool(self._store.get(key, False))

  def remove(self, key: str, block: bool = False) -> None:
    self._require_key(key)
    self._store.pop(key, None)
