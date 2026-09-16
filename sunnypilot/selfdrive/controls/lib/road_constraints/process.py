"""Restart policy scoped to the optional road service; other managed processes are unchanged."""

import time

from openpilot.system.manager.process import PythonProcess
from .runtime import should_run


class RoadInputProcess(PythonProcess):
  def __init__(self, *, clock=time.monotonic):
    super().__init__("roadinputd", "openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.roadinputd", should_run)
    self.clock = clock
    self.next_start = 0.0

  def start(self):
    if self.proc is not None and self.proc.exitcode is not None:
      self.stop()
    if self.proc is None and self.clock() < self.next_start:
      return
    if self.proc is None:
      self.next_start = self.clock() + 1.0
    super().start()
