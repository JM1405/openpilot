"""Android GPS FILE replay adapter. This is deliberately not a live clock mapper.

Boot-relative Android timestamps cannot be compared to a different device's clock.
For offline replay, preserve the recorded age and spacing on a synthetic timeline.
Every invalid record must clear the provider; never retain its preceding snapshot.
"""

from dataclasses import dataclass
from uuid import UUID

from .offline import Fix
from .measurements import parse_measurements


@dataclass(frozen=True)
class ReplayFix:
  status: str
  fix: Fix | None = None
  now: float | None = None
  new_session: bool = False


class RecordingReader:
  def __init__(self):
    self.session = None
    self.seen_sessions = set()
    self.origin = self.last_received = self.last_fix = self.sequence = None

  def decode(self, row) -> ReplayFix:
    if not isinstance(row, dict) or type(row.get("schema")) is not int or row["schema"] != 1 or row.get("type") != "fix":
      return ReplayFix("invalidRecord")
    session = row.get("session")
    try:
      if not isinstance(session, str) or str(UUID(session)) != session:
        return ReplayFix("invalidSession")
    except ValueError:
      return ReplayFix("invalidSession")
    integers = [row.get(k) for k in ("sequence", "fix_elapsed_ns", "received_elapsed_ns", "utc_ms")]
    if any(type(v) is not int or not 0 <= v <= 2**63 - 1 for v in integers) or integers[0] < 1:
      return ReplayFix("invalidRecordClock")
    sequence, observed, received, _ = integers
    new_session = session != self.session
    if new_session:
      if session in self.seen_sessions:
        return ReplayFix("sessionReplay")
      if sequence != 1:
        return ReplayFix("missingSessionStart")
      self.seen_sessions.add(session)
      self.session, self.origin = session, received
      self.sequence = self.last_received = self.last_fix = None
    if observed > received:
      return ReplayFix("futureFix")
    if self.sequence is not None:
      if sequence <= self.sequence or received <= self.last_received or observed <= self.last_fix:
        return ReplayFix("recordReplay")
      gap = sequence != self.sequence + 1
    else:
      gap = False
    self.sequence, self.last_received, self.last_fix = sequence, received, observed
    if gap:
      return ReplayFix("recordGap")
    if row.get("provider") != "gps" or row.get("mock") is not False:
      return ReplayFix("untrustedLocation")
    numbers = [row.get(k) for k in ("longitude", "latitude", "bearing_deg", "speed_mps", "accuracy_m", "bearing_accuracy_deg")]
    try:
      numbers = parse_measurements(numbers)
    except ValueError as exc:
      return ReplayFix(str(exc))
    now = 100.0 + (received - self.origin) / 1e9
    age = (received - observed) / 1e9
    if age > 0.2:
      return ReplayFix("staleFix")
    return ReplayFix("recordedFix", Fix(*numbers, now - age), now, new_session)
