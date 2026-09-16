"""Offline road derivation, run separately from the planner by optional roadinputd.

The source clock is the local derivation time, NOT the static map's update date.
Map/event dates are checked separately. Raw event coordinates never imply a
verified road/direction binding. No SDK, network or vehicle activation in this module.
"""

import json
import math
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path

from .contract import RoadConstraint, RoadContext, RoadInput, RoadKind, RoadLink, RoadSnapshot
from .measurements import MOVING_SPEED, parse_measurements
from .event_review import attributes, validate_review
from .curves import analyze as analyze_curves

EARTH_M = 6371008.8


def xy(lon: float, lat: float, origin: tuple[float, float]) -> tuple[float, float]:
  return (math.radians(lon - origin[0]) * EARTH_M * math.cos(math.radians(origin[1])), math.radians(lat - origin[1]) * EARTH_M)


def distance(a, b) -> float:
  return math.hypot(*xy(*b, a))


def angle_delta(a, b) -> float:
  return abs((a - b + 180.0) % 360.0 - 180.0)


def bearing(a, b) -> float:
  x, y = xy(*b, a)
  return math.degrees(math.atan2(x, y)) % 360.0


def project(point, points) -> tuple[float, float, float]:
  """Distance to polyline, directed along-line distance, local bearing (metres/degrees)."""
  return min(project_segments(point, points), key=lambda item: item[0], default=(math.inf, 0.0, 0.0))


def project_segments(point, points):
  """Keep alternatives available to reject self-crossing/overlapping road geometry."""
  travelled = 0.0
  for a, b in pairwise(points):
    bx, by = xy(*b, a)
    px, py = xy(*point, a)
    length = math.hypot(bx, by)
    if length < 1e-6:
      continue
    t = min(1.0, max(0.0, (px * bx + py * by) / length**2))
    gap = math.hypot(px - t * bx, py - t * by)
    yield gap, travelled + t * length, bearing(a, b)
    travelled += length


def recent(value: str, today: date, days: int) -> bool:
  try:
    return 0 <= (today - date.fromisoformat(value)).days <= days
  except (ValueError, TypeError):
    return False


@dataclass(frozen=True)
class Fix:
  lon: float
  lat: float
  bearing_deg: float | None
  speed_mps: float
  accuracy_m: float
  bearing_accuracy_deg: float | None
  observed_at: float  # already mapped into this process's monotonic clock


@dataclass(frozen=True)
class Link:
  id: str
  start: str
  end: str
  name: str
  points: tuple[tuple[float, float], ...]
  speed_kph: float
  updated: str
  road_use: str = "0"
  rest_veh: str = "0"
  connector: str = "0"

  @property
  def length(self):
    return sum(distance(a, b) for a, b in pairwise(self.points))

  @property
  def ref(self):
    return RoadLink(self.id, f"{self.start}>{self.end}")

  def usable(self, today, max_age):
    # National nodelink codebook: ROAD_USE 0=used, REST_VEH contains 1=passenger cars prohibited.
    return (
      self.road_use == "0"
      and self.rest_veh.isdigit()
      and "1" not in self.rest_veh
      and set(self.rest_veh) <= set("023456")
      and self.length > 2.0
      and recent(self.updated, today, max_age)
    )


def create_schema(db):
  db.executescript("""
    CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE links(pk INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, start TEXT, end TEXT,
      name TEXT, points TEXT, speed_kph REAL, updated TEXT, road_use TEXT, rest_veh TEXT, connector TEXT);
    CREATE INDEX next_link ON links(start);
    CREATE VIRTUAL TABLE bounds USING rtree(pk, minlon, maxlon, minlat, maxlat);
    CREATE TABLE events(id TEXT PRIMARY KEY, kind TEXT NOT NULL, lon REAL, lat REAL,
      target_kph REAL, updated TEXT, source TEXT NOT NULL, attributes TEXT NOT NULL,
      link_id TEXT, along_m REAL, verified INTEGER NOT NULL DEFAULT 0 CHECK(verified IN (0,1)));
    CREATE INDEX events_on_link ON events(link_id);
  """)


def insert_link(db, link: Link):
  cursor = db.execute(
    "INSERT INTO links(id,start,end,name,points,speed_kph,updated,road_use,rest_veh,connector) " + "VALUES(?,?,?,?,?,?,?,?,?,?)",
    (link.id, link.start, link.end, link.name, json.dumps(link.points), link.speed_kph, link.updated, link.road_use, link.rest_veh, link.connector),
  )
  lons, lats = zip(*link.points, strict=True)
  db.execute("INSERT INTO bounds VALUES(?,?,?,?,?)", (cursor.lastrowid, min(lons), max(lons), min(lats), max(lats)))


class RoadStore:
  def __init__(self, path):
    self.db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=.05)
    self.db.row_factory = sqlite3.Row
    try:
      self.metadata = dict(self.db.execute("SELECT key,value FROM metadata"))
    except Exception:
      self.db.close()
      raise

  def close(self):
    self.db.close()

  @staticmethod
  def link(row):
    return Link(
      row["id"],
      row["start"],
      row["end"],
      row["name"],
      tuple(tuple(p) for p in json.loads(row["points"])),
      row["speed_kph"],
      row["updated"],
      row["road_use"],
      row["rest_veh"],
      row["connector"],
    )

  def nearby(self, lon, lat, radius_m=45.0):
    dy = math.degrees(radius_m / EARTH_M)
    dx = dy / math.cos(math.radians(lat))
    rows = self.db.execute(
      "SELECT l.* FROM links l JOIN bounds b ON l.pk=b.pk " + "WHERE b.minlon<=? AND b.maxlon>=? AND b.minlat<=? AND b.maxlat>=? ORDER BY l.id",
      (lon + dx, lon - dx, lat + dy, lat - dy),
    )
    return [self.link(r) for r in rows]

  def successors(self, link):
    return [self.link(r) for r in self.db.execute("SELECT * FROM links WHERE start=? ORDER BY id", (link.end,))]

  def events(self, link):
    return self.db.execute("SELECT * FROM events WHERE link_id=? ORDER BY along_m,id", (link.id,)).fetchall()


@dataclass(frozen=True)
class Observation:
  status: str
  road_input: RoadInput | None = None
  link_id: str | None = None
  match_gap_m: float | None = None
  horizon_end: str | None = None
  unverified_events: int = 0
  event_review_reasons: tuple[str, ...] = ()
  curve_candidates: int = 0
  curve_rejections: tuple[str, ...] = ()


class OfflineProvider:
  def __init__(self, store: RoadStore, *, map_max_days=730, event_max_days=365, horizon_m=1000.0):
    self.store = store
    self.map_max_days, self.event_max_days, self.horizon_m = map_max_days, event_max_days, horizon_m
    self.session, self.version, self.sequence = str(uuid.uuid4()), 0, 0
    self.previous = None
    self.previous_fix = None
    self.last_path = None
    self.hold_anchor = None
    self.holding = False
    self.route_identity = None

  def reset(self, status):
    self.previous = self.previous_fix = self.last_path = None
    self.hold_anchor = None
    self.holding = False
    self.version += 1
    return Observation(status)

  def observe(self, fix: Fix, *, now: float, today: date, route=None) -> Observation:
    identity = (route.state, route.identity) if route is not None else ('none', '')
    if self.route_identity is not None and identity != self.route_identity:
      self.reset('routeChanged')
    self.route_identity = identity
    if route is not None and (route.state == 'pending' or (route.state == 'active' and now >= route.valid_until)):
      return self.reset(route.reason or 'routeExpired')
    if not all(type(v) in (int, float) and 0 <= v < 1e12 for v in (fix.observed_at, now)):
      return self.reset("invalidFix")
    try:
      values = parse_measurements((fix.lon, fix.lat, fix.bearing_deg, fix.speed_mps, fix.accuracy_m, fix.bearing_accuracy_deg))
    except ValueError as exc:
      return self.reset('invalidFix' if str(exc) == 'missingOrInvalidMeasurement' else str(exc))
    fix = Fix(*values, fix.observed_at)
    if not 0 <= now - fix.observed_at <= 0.2:
      return self.reset("staleFix")
    if self.previous_fix is not None:
      dt = fix.observed_at - self.previous_fix.observed_at
      if dt <= 0:
        return self.reset("fixReplay")
      if dt > 1.0:
        self.reset("gap")
      elif distance((fix.lon, fix.lat), (self.previous_fix.lon, self.previous_fix.lat)) > (
        max(fix.speed_mps, self.previous_fix.speed_mps) * dt + 2 * (fix.accuracy_m + self.previous_fix.accuracy_m) + 5.0
      ):
        return self.reset("positionJump")

    if fix.speed_mps < MOVING_SPEED:
      return self.hold_at_low_speed(fix, today)
    if self.holding:
      self.previous = self.last_path = self.hold_anchor = None
      self.holding = False

    corridor = None
    horizon_m = self.horizon_m
    if route is not None and route.state == 'active':
      from .route_hint import RouteCorridor
      try:
        corridor = RouteCorridor(route.points, fix)
      except ValueError as error:
        return self.reset(str(error))
      horizon_m = min(horizon_m, corridor.horizon)
      if horizon_m < 30.:
        return self.reset('routeCoverageBoundary')

    candidates, nearby = [], []
    for link in self.store.nearby(fix.lon, fix.lat):
      gap, along, course = project((fix.lon, fix.lat), link.points)
      nearby.append((link, gap, course))
      delta = angle_delta(course, fix.bearing_deg)
      if gap <= max(12.0, fix.accuracy_m * 2) and delta <= 35.0:
        candidates.append((gap + 0.35 * delta, link.id, gap, along, link))
    candidates.sort()
    if not candidates:
      return self.reset("noRoadMatch")
    best = candidates[0]
    # A heading score cannot settle overlapping position uncertainty. Prior road
    # identity is deliberately not a bonus capable of defeating this veto.
    if len(candidates) > 1 and (
      candidates[1][0] - best[0] < max(4.0, fix.accuracy_m) or any(c[2] <= best[2] + 2 * fix.accuracy_m + 2.0 for c in candidates[1:])
    ):
      return self.reset("ambiguousRoad")
    _, _, gap, along, link = best
    if not link.usable(today, self.map_max_days):
      return self.reset("unusableOrOldRoad")
    margin = max(8.0, 2 * fix.accuracy_m)
    if any(
      abs(other_along - along) > 2 * margin and other_gap <= gap + 2 * fix.accuracy_m + 2.0
      for other_gap, other_along, _ in project_segments((fix.lon, fix.lat), link.points)
    ):
      return self.reset('ambiguousRoadGeometry')
    # Without independent height/route evidence a nearby crossing may be a turn,
    # intersection or overpass. Do not let a stale bearing pick through it.
    if any(other.id != link.id and other_gap <= margin and 35.0 < angle_delta(course, fix.bearing_deg) < 145.0 for other, other_gap, course in nearby):
      return self.reset('junctionUncertain')
    if along <= margin or link.length - along <= margin:
      return self.reset('roadBoundaryUncertain')

    if corridor is not None and not corridor.supports(link, along, min(link.length, along+horizon_m)):
      return self.reset('routeRoadMismatch')

    old = self.previous
    old_fix = self.previous_fix
    self.previous, self.previous_fix = (link, along), fix
    if old is None:
      return Observation("warmingUp", link_id=link.id, match_gap_m=gap)
    old_link, old_along = old
    budget = max(fix.speed_mps, old_fix.speed_mps) * (fix.observed_at - old_fix.observed_at) + 2 * (fix.accuracy_m + old_fix.accuracy_m) + 5.0
    if old_link.id == link.id and along < old_along:
      return self.reset("backwardsProgress")
    if old_link.id == link.id and along - old_along > budget:
      return self.reset('implausibleProgress')
    if old_link.id != link.id:
      if old_link.end != link.start:
        return self.reset("disconnectedTransition")
      if distance(old_link.points[-1], link.points[0]) > 5.0:
        return self.reset('transitionGeometryGap')
      travelled = old_link.length - old_along + along
      if travelled > budget:
        return self.reset('implausibleTransition')
      self.version += 1
      self.hold_anchor = self.last_path = None
      return Observation('transitionConfirming', link_id=link.id, match_gap_m=gap)
    # Only an independently matched route may confirm one unique fork branch.
    path, total, end_reason = [link], link.length - along, "distance"
    while total < horizon_m and len(path) < 32:
      successors = self.store.successors(path[-1])
      if len(successors) != 1:
        if corridor is None or not successors:
          end_reason = "fork" if successors else "endOrCoverageBoundary"
          break
        matches = [n for n in successors if corridor.supports(n, 0., min(n.length, 250., horizon_m-total))]
        if len(matches) != 1:
          end_reason = 'routeBranchAmbiguous'
          break
        nxt = matches[0]
      else:
        nxt = successors[0]
      if nxt.id in {p.id for p in path}:
        end_reason = "loop"
        break
      if not nxt.usable(today, self.map_max_days):
        end_reason = "unusableOrOldRoad"
        break
      if distance(path[-1].points[-1], nxt.points[0]) > 5.0:
        end_reason = "geometryGap"
        break
      if angle_delta(bearing(*path[-1].points[-2:]), bearing(*nxt.points[:2])) > 65.0:
        end_reason = "unconfirmedTurn"
        break
      if corridor is not None and not corridor.supports(nxt, 0., min(nxt.length, horizon_m-total)):
        end_reason = 'routeRoadMismatch'
        break
      path.append(nxt)
      total += nxt.length

    refs = tuple(p.ref for p in path)
    if self.last_path is not None and self.last_path != refs:
      self.version += 1
    self.last_path = refs
    constraints, offset, unverified = [], -along, 0
    review_reasons = set()
    curve_count, curve_reasons = 0, set()
    for road in path:
      end = min(offset + road.length, horizon_m)
      # CONNECT is a ramp flag, not a virtual-link flag. Ramp speeds are withheld in this first prototype.
      if road.connector == "0" and 10 <= road.speed_kph <= 130 and end > max(0.0, offset):
        constraints.append(RoadConstraint(f"its:{road.id}:limit", RoadKind.SPEED_LIMIT, road.ref, max(0.0, offset), end, road.speed_kph / 3.6))
      if road.connector != '0':
        curve_reasons.add('rampUnconfirmed')
      else:
        geometry = analyze_curves(road.points)
        curve_reasons.update(geometry.rejections)
        for index, bend in enumerate(geometry.bends):
          start, finish = offset + bend.start_m, offset + bend.end_m
          # Keep the whole supported segment. Do not invent its exit at the horizon.
          if finish > 0 and start <= horizon_m and finish <= 10000. and (corridor is None or finish <= horizon_m):
            constraints.append(RoadConstraint(f'its:{road.id}:curve:{index}', RoadKind.CURVE,
              road.ref, start, finish, min(130 / 3.6, bend.target_speed)))
            curve_count += 1
      for event in self.store.events(road):
        try:
          target = attributes(event).get('event_review', {}).get('target', {})
          neighbors = self.store.nearby(target['longitude'], target['latitude'], 15.) if target else []
          reason = validate_review(event, road, neighbors, self.store.metadata.get('dataset_id'), today)
        except (ValueError, TypeError, KeyError, AttributeError):
          reason = 'invalidReview'
        if reason:
          unverified += 1
          review_reasons.add(reason)
          continue
        if not recent(event["updated"], today, self.event_max_days):
          continue
        target, at = event["target_kph"], event["along_m"]
        if target is None or at is None or not (0 < target <= 130 and 0 <= at <= road.length):
          continue
        start = offset + at
        if 0 <= start <= horizon_m and event["kind"] in ("camera", "bump"):
          constraints.append(RoadConstraint(event["id"], RoadKind(event["kind"]), road.ref, start, start, target / 3.6))
      offset += road.length
    if len(constraints) > 32:
      return self.reset("tooManyConstraints")
    self.sequence += 1
    self.hold_anchor = (link, along, fix)
    context = RoadContext(self.session, self.version, refs, along, fix.observed_at)
    snapshot = RoadSnapshot(
      "offline-derived:" + self.store.metadata.get("dataset_id", "unknown"), self.session, self.version, self.sequence, now, now, along, tuple(constraints)
    )
    return Observation("derived", RoadInput(snapshot, context), link.id, gap, end_reason, unverified,
                       tuple(sorted(review_reasons)), curve_count, tuple(sorted(curve_reasons)))

  def hold_at_low_speed(self, fix, today):
    # Identity only: no road constraints at low speed, and fresh moving samples
    # must reconfirm on resume. The anchor lifetime never follows GPS heartbeats.
    if self.hold_anchor is None:
      return self.reset('headingUnavailableAtLowSpeed')
    link, _, anchor = self.hold_anchor
    if fix.observed_at - anchor.observed_at > 5.0:
      return self.reset('lowSpeedHoldExpired')
    gap, along, _ = project((fix.lon, fix.lat), link.points)
    if not link.usable(today, self.map_max_days):
      return self.reset('unusableOrOldRoad')
    if (
      gap > max(4.0, fix.accuracy_m)
      or min(along, link.length - along) <= max(8.0, 2 * fix.accuracy_m)
      or distance((fix.lon, fix.lat), (anchor.lon, anchor.lat)) > 5.0 + fix.accuracy_m + anchor.accuracy_m
    ):
      return self.reset('lowSpeedPositionUncertain')
    for other in self.store.nearby(fix.lon, fix.lat):
      if other.id != link.id and project((fix.lon, fix.lat), other.points)[0] <= gap + 2 * fix.accuracy_m + 2.0:
        return self.reset('lowSpeedRoadAmbiguous')
    if not self.holding:
      self.version += 1
    self.previous = self.last_path = None
    self.previous_fix, self.holding = fix, True
    return Observation('lowSpeedHold', link_id=link.id, match_gap_m=gap)
