"""Experimental display suppression only; not identity tracking or control input.

Development thresholds, unvalidated on current-model/vehicle data. The caller
must gate freshness and invalidate on missing inputs. Camera redraws never count
as new observations. No position, velocity or color is carried into the marker.
"""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LeadObservation:
  stamp: int
  frame: int
  capture: int
  present: bool
  distance: float
  lateral: float
  velocity: float
  probability: float


class LeadContinuityGate:
  MIN_PROBABILITY = .9
  MIN_SAMPLES = 3
  MIN_SPAN_NS = 100_000_000
  MAX_GAP_NS = 150_000_000
  RANGE_FLOOR = 5.
  RANGE_FRACTION = .2

  def __init__(self):
    self.water = (0, -1, 0)
    self.last = None
    self.previous = None
    self.since = 0
    self.count = 0
    self.reason = 'lead_confirming'

  def invalidate(self, reason='lead_unavailable'):
    # Preserve the consumed packet/high-water marks. Restoring validity of the
    # same packet cannot resurrect a previously visible or confirming candidate.
    self.previous = None
    self.since = self.count = 0
    self.reason = reason
    return reason

  def update(self, sample):
    key = (sample.stamp, sample.frame, sample.capture)
    if self.last is not None and key == (self.last.stamp, self.last.frame, self.last.capture):
      if sample != self.last:
        return self.invalidate('lead_inconsistent')
      return self.reason
    if any(new <= old for new, old in zip(key, self.water, strict=True)):
      return self.invalidate('lead_replayed')
    self.water = key
    self.last = sample
    if (sample.capture > sample.stamp or not sample.present or
        not all(math.isfinite(v) for v in (sample.distance, sample.lateral, sample.velocity, sample.probability)) or
        not 0 < sample.distance <= 200 or not 0 <= sample.probability <= 1):
      return self.invalidate()
    if sample.probability < self.MIN_PROBABILITY:
      return self.invalidate('lead_low_confidence')
    previous = self.previous
    discontinuity = False
    if previous is not None:
      gap = sample.capture - previous.capture
      dt = gap / 1e9
      distance_error = sample.distance - previous.distance - .5 * (sample.velocity + previous.velocity) * dt
      discontinuity = (gap > self.MAX_GAP_NS or
                       abs(distance_error) > max(self.RANGE_FLOOR, self.RANGE_FRACTION * min(sample.distance, previous.distance)) or
                       abs(sample.lateral - previous.lateral) > .75 + 3 * dt)
    if previous is None or discontinuity:
      self.since, self.count = sample.capture, 1
    else:
      self.count += 1
    self.previous = sample
    ready = self.count >= self.MIN_SAMPLES and sample.capture - self.since >= self.MIN_SPAN_NS
    self.reason = 'candidate' if ready else ('lead_discontinuity' if discontinuity else 'lead_confirming')
    return self.reason
