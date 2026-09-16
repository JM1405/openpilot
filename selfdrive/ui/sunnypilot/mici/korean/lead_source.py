"""Opt-in visual lead qualification. Source labels are not object identities.

Radar-only points do not establish a vehicle image box. For associated leads,
use current model lateral geometry, not noisy radar lateral position. Thresholds
are development assumptions, not calibrated confidence or vehicle approval.
"""
import math
from dataclasses import dataclass

from openpilot.selfdrive.ui.sunnypilot.mici.korean.lead_continuity import LeadContinuityGate, LeadObservation

# Same longitudinal origin conversion used by radard.get_RadarState_from_vision.
RADAR_TO_CAMERA = 1.52


@dataclass(frozen=True)
class SourceObservation(LeadObservation):
  source: str
  track_id: int


@dataclass(frozen=True)
class SourceDecision:
  source: str
  reason: str
  lateral: float


def qualify(raw, model):
  source = 'radar_vision' if raw.radar else 'vision'
  if raw.radar and raw.modelProb == 0:
    return 'radar_only', 'lead_radar_only', math.nan, 0.
  if raw.radar and raw.radarTrackId < 0:
    return 'unknown', 'lead_source_unknown', math.nan, 0.
  leads = model.get('leadsV3', [])
  if not leads:
    return source, 'lead_visual_missing', math.nan, 0.
  lead = leads[0]  # leadOne is paired to the current-time first model lead.
  fields = ('x', 'y', 'xStd', 'yStd', 't')
  if any(not lead.get(name) for name in fields):
    return source, 'lead_visual_missing', math.nan, 0.
  x, y, xs, ys, t = (lead[name][0] for name in fields)
  probability, prob_time = lead.get('prob', math.nan), lead.get('probTime', math.nan)
  if (not all(math.isfinite(v) for v in (x, y, xs, ys, t, probability, prob_time, raw.modelProb)) or
      xs < 0 or ys < 0 or t != 0 or prob_time != 0 or not 0 <= probability <= 1 or not 0 <= raw.modelProb <= 1):
    return source, 'lead_visual_invalid', math.nan, 0.
  distance = x - RADAR_TO_CAMERA
  if not 0 < distance <= 200 or not math.isfinite(raw.dRel):
    return source, 'lead_visual_invalid', math.nan, 0.
  if abs(raw.dRel - distance) >= max(5., .25 * distance):
    return source, 'lead_visual_mismatch', math.nan, 0.
  # One reported lateral standard deviation larger than half the assumed rear
  # width does not support this box. No claim that std is calibrated coverage.
  if ys > .9 or xs > max(5., .2 * distance):
    return source, 'lead_visual_uncertain', math.nan, 0.
  return source, 'candidate', -y, min(probability, raw.modelProb)


class LeadSourceGate(LeadContinuityGate):
  def update_source(self, raw, model, stamp):
    source, eligibility, lateral, probability = qualify(raw, model)
    sample = SourceObservation(stamp, model.get('frameId', -1), model.get('timestampEof', 0), raw.present,
                             raw.dRel, lateral, raw.vRel, probability, source,
                             raw.radarTrackId if raw.radar else -1)
    previous = self.previous
    forward = all(new > old for new, old in zip((sample.stamp, sample.frame, sample.capture), self.water, strict=True))
    changed = (forward and previous is not None and
               (sample.source, sample.track_id) != (previous.source, previous.track_id))
    if changed:
      self.invalidate()
    reason = self.update(sample)  # consume even a rejected packet; redraws never confirm
    if eligibility != 'candidate':
      reason = self.invalidate(eligibility)
    elif changed and reason == 'lead_confirming':
      self.reason = reason = 'lead_source_changed'
    return SourceDecision(source, reason, lateral)
