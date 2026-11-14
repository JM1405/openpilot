from __future__ import annotations

import py_compile
from pathlib import Path

from openpilot.sunnypilot.koranipilot.catalog import load_catalog
from openpilot.sunnypilot.koranipilot.tests.fake_params import REPO_ROOT, parse_params_keys_h


def test_all_74_catalog_keys_exist_in_params_keys_h():
  schema = parse_params_keys_h()
  catalog = load_catalog()
  rows = catalog["rows"]
  assert len(rows) == 74
  missing = [r["key"] for r in rows if r["key"] not in schema]
  assert missing == [], f"Unregistered keys in settings_catalog.json: {missing}"


def test_hangul_font_present():
  font_dir = REPO_ROOT / "sunnypilot" / "koranipilot" / "fonts"
  assert (font_dir / "AlertSans.ttf").stat().st_size > 100_000
  assert (font_dir / "OFL.txt").is_file()
  assert (font_dir / "provenance.json").is_file()


def test_all_modified_and_added_python_files_compile():
  paths = [
    REPO_ROOT / "system" / "manager" / "process_config.py",
    REPO_ROOT / "sunnypilot" / "selfdrive" / "controls" / "lib" / "smart_cruise_control" / "vision_controller.py",
    REPO_ROOT / "sunnypilot" / "selfdrive" / "controls" / "lib" / "longitudinal_planner.py",
    REPO_ROOT / "selfdrive" / "ui" / "sunnypilot" / "mici" / "korani_ui.py",
    REPO_ROOT / "selfdrive" / "ui" / "mici" / "layouts" / "home.py",
    REPO_ROOT / "selfdrive" / "ui" / "sunnypilot" / "mici" / "layouts" / "settings.py",
    REPO_ROOT / "selfdrive" / "ui" / "mici" / "onroad" / "augmented_road_view.py",
    *(REPO_ROOT / "sunnypilot" / "koranipilot").glob("*.py"),
  ]
  for path in paths:
    assert path.is_file(), f"Missing expected Python file: {path}"
    py_compile.compile(str(path), doraise=True)
