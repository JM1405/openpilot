"""Shared observer: raw fixes match roads; motion never confirms a road.

sample() returns an observation-only position. anchor_road retains raw-confirmed
metadata for the typed runtime adapter, without producing actuator commands.
Only an independently confirmed SAME link may carry an estimated position.
"""
from dataclasses import dataclass

from .motion import MAX_ANCHOR_AGE, MotionEstimate, MotionTracker
from .offline import OfflineProvider, angle_delta, project, project_segments


@dataclass(frozen=True)
class ShadowPosition:
  status: str
  estimate: MotionEstimate | None = None
  link_id: str | None = None
  progress_m: float | None = None
  observation_only: bool = True


class MotionRoadObserver:
  def __init__(self, store, *, today):
    self.tracker = MotionTracker()
    self.provider = OfflineProvider(store, max_fix_interval_s=MAX_ANCHOR_AGE)
    self.store, self.today = store, today
    self.link = None
    self.anchor_road = None
    self.route_identity = None
    self.route = None
    self.route_dirty = False
    self.route_blocked = False
    self.route_independent = False
    self.status = 'waitingForFix'

  def revoke(self, reason):
    self.tracker.revoke(reason)
    self.provider.reset(reason)
    self.link = None
    self.anchor_road = None
    self.route_dirty = False
    self.route_independent = False
    self.status = reason

  def set_route(self, route):
    identity = (route.state, route.identity) if route is not None else ('none', '')
    if self.route_identity is not None and self.route_identity != identity:
      self.link = self.anchor_road = None
      self.route_dirty = True
      self.route_independent = False
      self.status = 'routeChanged'
    self.provider.set_route(route)
    self.route_identity, self.route = identity, route

  def push_motion(self, sample, *, now):
    accepted = self.tracker.push_motion(sample, now=now)
    if not accepted or self.tracker.anchor is None:
      self.provider.reset(self.tracker.status)
      self.link = self.anchor_road = None
    return accepted

  def accept_fix(self, fix, *, now, clock_uncertainty_s=0.):
    if not self.tracker.accept_fix(fix, now=now, clock_uncertainty_s=clock_uncertainty_s):
      self.provider.reset(self.tracker.status)
      self.link = self.anchor_road = None
      self.status = self.tracker.status
      return False
    if not self.tracker.confirmed:
      self.provider.reset('warmingUp')
    observation = self.provider.observe(fix, now=now, today=self.today, route=self.route)
    self.route_dirty = False
    self.route_blocked = self._route_unavailable(now)
    self.route_independent = observation.route_independent
    self.anchor_road = observation.road_input
    self.status = observation.status
    self.link = self.provider.previous[0] if observation.road_input is not None else None
    return self.link is not None

  def _route_unavailable(self, now):
    return self.route is not None and (self.route.state == 'pending' or
      (self.route.state == 'active' and now >= self.route.valid_until))

  def sample(self, now):
    unavailable = self._route_unavailable(now)
    if unavailable != self.route_blocked:
      # Rebuild current-road-only input on expiry, and the new path on recovery.
      # Independent GPS/motion must not acquire a new lifetime in either case.
      self.link = self.anchor_road = None
      self.route_dirty = True
      self.route_independent = False
    self.route_blocked = unavailable
    estimate = self.tracker.estimate(now)
    if estimate is None:
      self.status = self.tracker.status
      if self.tracker.anchor is None:
        self.link = self.anchor_road = None
        self.provider.reset(self.status)
      return ShadowPosition(self.status)
    if self.route_dirty:
      observation = self.provider.revalidate_route(now=now, today=self.today, route=self.route)
      self.route_dirty = False
      self.anchor_road = observation.road_input
      self.route_independent = observation.route_independent
      self.status = observation.status
      self.link = self.provider.previous[0] if observation.road_input is not None else None
    if self.link is None:
      return ShadowPosition(self.status)
    link = self.link
    point = (estimate.lon, estimate.lat)
    gap, along, course = project(point, link.points)
    radius = estimate.error_radius_m
    margin = max(8., 2*radius)
    reason = None
    if gap > max(12., 2*radius) or angle_delta(course, estimate.bearing_deg) > 35.:
      reason = 'estimatedRoadMismatch'
    elif min(along, link.length-along) <= margin:
      reason = 'estimatedRoadBoundary'
    elif any(abs(other-along) > 2*margin and other_gap <= gap+2*radius+2.
             for other_gap, other, _ in project_segments(point, link.points)):
      reason = 'estimatedGeometryAmbiguous'
    elif any(other.id != link.id and project(point, other.points)[0] <= gap+2*radius+2.
             for other in self.store.nearby(*point, radius_m=60.)):
      reason = 'estimatedRoadAmbiguous'
    if reason:
      self.revoke(reason)
      return ShadowPosition(reason)
    self.status = 'currentRoadOnly' if self.route_independent else 'shadowPosition'
    return ShadowPosition(self.status, estimate, link.id, along)
