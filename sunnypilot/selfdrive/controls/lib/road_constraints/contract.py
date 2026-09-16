from dataclasses import dataclass
from enum import StrEnum
import math


class RoadKind(StrEnum):
  SPEED_LIMIT = "speedLimit"
  CAMERA = "camera"
  SECTION = "section"
  BUMP = "bump"
  CURVE = "curve"


@dataclass(frozen=True)
class RoadLink:
  road_id: str
  direction: str


@dataclass(frozen=True)
class RoadConstraint:
  event_id: str
  kind: RoadKind
  link: RoadLink
  start_m: float
  end_m: float
  target_speed: float


@dataclass(frozen=True)
class RoadContext:
  """Trusted ego path match, refreshed independently of event delivery.

  path contains only the confirmed current/ahead corridor, including in free drive.
  progress_m is cumulative path travel in this session/version, not GPS straight-line
  distance. A reroute, direction change or progress reset requires a new version.
  Position is at observed_at; the planner advances fresh samples to its current
  time. Adapters must not also project it while retaining the older timestamp.
  """
  session: str
  path_version: int
  path: tuple[RoadLink, ...]
  progress_m: float
  observed_at: float
  confirmed: bool = True


@dataclass(frozen=True)
class RoadSnapshot:
  """Complete replacement, never an event delta. Empty events explicitly clear it.

  Distances are relative to reference_progress_m. source_at must be mapped to the
  local monotonic clock by a verified adapter; None means unknown, not received_at.
  Sequence increases on every change, including refreshes and removal of events.
  """
  source: str
  session: str
  path_version: int
  sequence: int
  source_at: float | None
  received_at: float
  reference_progress_m: float
  constraints: tuple[RoadConstraint, ...]


@dataclass(frozen=True)
class RoadInput:
  snapshot: RoadSnapshot
  context: RoadContext


@dataclass(frozen=True)
class InputLimits:
  source_age: float = 2.0
  receive_age: float = 2.0
  context_age: float = 0.2
  future_tolerance: float = 0.01
  max_events: int = 32
  max_distance: float = 10000.0
  max_speed: float = 70.0


class RoadInputValidator:
  def __init__(self, limits: InputLimits | None = None):
    self.limits = limits or InputLimits()
    self.last_snapshot: RoadSnapshot | None = None
    self.last_context: RoadContext | None = None

  def validate(self, road_input: RoadInput | None, now: float) -> str:
    if road_input is None:
      return "noInput"
    s, c = road_input.snapshot, road_input.context
    limits = self.limits
    if not math.isfinite(now):
      return "invalidClock"
    if not c.confirmed or not c.session or not c.path or len(c.path) > 64:
      return "unconfirmedPath"
    if any(not link.road_id or not link.direction for link in c.path) or len(set(c.path)) != len(c.path):
      return "invalidPath"
    if not s.source or (s.session, s.path_version) != (c.session, c.path_version):
      return "pathMismatch"
    if c.path_version < 0 or s.sequence < 0:
      return "invalidVersion"
    if s.source_at is None:
      return "unknownSourceTime"
    for stamp, max_age, label in ((s.source_at, limits.source_age, "source"),
                                   (s.received_at, limits.receive_age, "receive"),
                                   (c.observed_at, limits.context_age, "context")):
      if not math.isfinite(stamp) or stamp < 0 or stamp - now > limits.future_tolerance:
        return label + "Clock"
      if now - stamp > max_age:
        return label + "Stale"
    if s.source_at > s.received_at + limits.future_tolerance:
      return "sourceAfterReceive"
    if not all(math.isfinite(x) and x >= 0 for x in (c.progress_m, s.reference_progress_m)):
      return "invalidProgress"
    if c.progress_m < s.reference_progress_m:
      return "progressBeforeSnapshot"
    if self.last_context is not None:
      old = self.last_context
      if (c.session, c.path_version) == (old.session, old.path_version):
        if c.observed_at < old.observed_at or c.progress_m < old.progress_m:
          return "progressReplay"
    if self.last_snapshot is not None:
      old = self.last_snapshot
      if (s.source, s.session, s.path_version) == (old.source, old.session, old.path_version):
        if s.sequence < old.sequence or (s.sequence == old.sequence and s != old):
          return "snapshotReplay"
        if s.source_at < old.source_at or s.received_at < old.received_at:
          return "timestampReplay"
    if len(s.constraints) > limits.max_events:
      return "tooManyEvents"
    event_ids = set()
    for event in s.constraints:
      if not event.event_id or event.event_id in event_ids:
        return "invalidEventId"
      event_ids.add(event.event_id)
      if not isinstance(event.kind, RoadKind):
        return "invalidKind"
      if event.link not in c.path:
        return "eventOutsidePath"
      if not all(math.isfinite(x) for x in (event.start_m, event.end_m, event.target_speed)):
        return "nonfiniteEvent"
      if not 0 < event.target_speed <= limits.max_speed:
        return "invalidSpeed"
      if not -limits.max_distance <= event.start_m <= event.end_m <= limits.max_distance:
        return "invalidDistance"
      if event.kind == RoadKind.CAMERA and event.start_m != event.end_m:
        return "invalidPoint"
      if event.kind in (RoadKind.SPEED_LIMIT, RoadKind.SECTION, RoadKind.CURVE) and event.start_m == event.end_m:
        return "emptySegment"
    self.last_snapshot, self.last_context = s, c
    return ""
