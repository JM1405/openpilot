from __future__ import annotations

import pytest

from openpilot.sunnypilot.koranipilot.tests.fake_params import FakeParams


@pytest.fixture(autouse=True)
def isolated_korani_dirs(tmp_path, monkeypatch):
  cfg_dir = tmp_path / "cfg"
  shm_dir = tmp_path / "shm"
  cfg_dir.mkdir(parents=True, exist_ok=True)
  shm_dir.mkdir(parents=True, exist_ok=True)
  monkeypatch.setenv("KORANIPILOT_DIR", str(cfg_dir))
  monkeypatch.setenv("KORANIPILOT_SHM_DIR", str(shm_dir))
  return cfg_dir, shm_dir


@pytest.fixture()
def fake_params():
  return FakeParams()
