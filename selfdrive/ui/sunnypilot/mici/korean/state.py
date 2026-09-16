"""Display contract, independent of messaging, rendering and vehicle control.

Times use one monotonic clock. Coordinates describe an approximate projected
lead frame, not a detector's vehicle bounding box. A future live adapter must
validate calibration and message freshness before constructing these inputs.
"""
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from openpilot.selfdrive.ui.sunnypilot.mici.korean.alerts import DrivingAlert


class EventKind(StrEnum):
  CAMERA = 'camera'
  BUMP = 'bump'
  CURVE_LEFT = 'curve_left'
  TURN_RIGHT = 'turn_right'
  EXIT_RIGHT = 'exit_right'
  SECTION = 'section'


@dataclass(frozen=True)
class Lead:
  target: str
  timestamp: float
  distance: float
  relative_speed: float
  # x/y are normalized to the road viewport; width/height are approximate.
  x: float = 0.50
  y: float = 0.52
  width: float = 0.14
  height: float = 0.25
  present: bool = True


@dataclass(frozen=True)
class Navigation:
  timestamp: float
  connected: bool = False
  route_valid: bool = False
  limit: float | None = None


@dataclass(frozen=True)
class RoadEvent:
  kind: EventKind
  timestamp: float
  distance: float
  average_speed: float | None = None


@dataclass(frozen=True)
class Snapshot:
  timestamp: float
  ego_speed: float  # m/s
  lateral_active: bool = False
  longitudinal_active: bool = False
  set_speed: float | None = None  # km/h, never the current vehicle speed
  mode: str = 'E2E'
  driver_attentive: bool | None = True
  steering_usage: float = 0.0
  lead: Lead | None = None
  navigation: Navigation | None = None
  event: RoadEvent | None = None
  intervention: bool = False  # supplied alert, not inferred from lead color
  alert: DrivingAlert | None = None
  alert_available: bool = True


@dataclass(frozen=True)
class Display:
  lateral_active: bool
  longitudinal_active: bool
  set_speed: float | None
  mode: str
  driver_attentive: bool | None
  steering_usage: float
  lead: Lead | None
  lead_emphasis: bool
  navigation_state: str
  limit: float | None
  event: RoadEvent | None
  intervention: bool
  stale: bool
  alert: DrivingAlert | None = None
  alert_available: bool = True


def fresh(timestamp: float, now: float, max_age: float) -> bool:
  return isfinite(timestamp) and isfinite(now) and 0 <= now - timestamp <= max_age


def speed_or_none(speed: float | None) -> float | None:
  return speed if speed is not None and isfinite(speed) and 0 < speed < 250 else None


def valid_lead(lead: Lead | None, now: float) -> bool:
  if lead is None or not lead.present or not lead.target or not fresh(lead.timestamp, now, 0.5):
    return False
  if not all(isfinite(v) for v in (lead.distance, lead.relative_speed, lead.x, lead.y, lead.width, lead.height)):
    return False
  return (0 < lead.distance <= 200 and 0 < lead.width <= 0.5 and 0 < lead.height <= 0.6 and
          lead.width / 2 <= lead.x <= 1 - lead.width / 2 and lead.height / 2 <= lead.y <= 1 - lead.height / 2)


class PreviewAttention:
  """UNVALIDATED simulation-only color experiment, never a brake/FCW decision.

  Enter: closing >= 2 m/s and TTC < 3 s, or moving > 5 m/s with
  time gap < 0.7 s. Exit margins avoid rapid color flicker. The numbers
  are test stimuli, not approved vehicle thresholds. No data -> no marker.
  """
  def __init__(self):
    self.target: str | None = None
    self.emphasized = False

  def reset(self):
    self.target = None
    self.emphasized = False

  def update(self, lead: Lead | None, ego_speed: float) -> bool:
    if lead is None or not isfinite(ego_speed) or ego_speed < 0:
      self.reset()
      return False
    if lead.target != self.target:
      self.reset()
      self.target = lead.target
    closing = max(0.0, -lead.relative_speed)
    ttc = lead.distance / closing if closing > 0 else float('inf')
    gap = lead.distance / ego_speed if ego_speed > 5 else float('inf')
    if self.emphasized:
      self.emphasized = (closing >= 1 and ttc < 4) or gap < 1.0
    else:
      self.emphasized = (closing >= 2 and ttc < 3) or gap < 0.7
    return self.emphasized


class DisplayController:
  def __init__(self, attention: PreviewAttention | None = None):
    # Actual UI has no invented approach threshold by default.
    self.attention = attention

  def update(self, snapshot: Snapshot, now: float) -> Display:
    stale = not fresh(snapshot.timestamp, now, 0.5)
    lead = snapshot.lead if not stale and valid_lead(snapshot.lead, now) else None
    emphasis = self.attention.update(lead, snapshot.ego_speed) if self.attention else False
    nav = snapshot.navigation
    nav_fresh = not stale and nav is not None and fresh(nav.timestamp, now, 3.0)
    nav_state = 'active' if nav_fresh and nav.connected and nav.route_valid else (
      'waiting' if nav_fresh and nav.connected else 'lost')
    limit = speed_or_none(nav.limit) if nav_state == 'active' else None
    event = snapshot.event
    if (nav_state != 'active' or event is None or not fresh(event.timestamp, now, 3.0) or
        not isfinite(event.distance) or event.distance < 0):
      event = None
    if event is not None and event.kind == EventKind.SECTION and speed_or_none(event.average_speed) is None:
      event = None
    # The alert service has its own clock, independent of carState/nav.
    available = snapshot.alert_available and (snapshot.alert is None or snapshot.alert.fresh(now))
    alert = snapshot.alert if available else None
    intervention = alert.alertStatus == 'critical' if alert else snapshot.intervention and snapshot.alert is None
    if alert or intervention:
      event, lead, emphasis = None, None, False
    usage = snapshot.steering_usage
    return Display(
      not stale and snapshot.lateral_active, not stale and snapshot.longitudinal_active,
      speed_or_none(snapshot.set_speed) if not stale else None,
      snapshot.mode if not stale and snapshot.mode in ('E2E', 'ACC', 'SCC', 'MADS') else '—',
      snapshot.driver_attentive if not stale else None,
      max(-1.0, min(1.0, usage)) if not stale and isfinite(usage) else 0.0,
      lead, emphasis, nav_state, limit, event, intervention, stale, alert, available,
    )
