"""Display-only ground estimate from one already paired, fresh model message.

The plan is sampled in time and may stop before the lead. Lane lines are sampled
in distance and already carry ground z (native renderer applies no height offset).
Lane probability/std and agreement checks are development gates, not calibrated
vertical uncertainty. Never extrapolate, substitute a flat plane, or reuse z.
"""
from dataclasses import dataclass
import math

import numpy as np

from openpilot.selfdrive.ui.sunnypilot.mici.korean.projection import RADAR_OFFSET


@dataclass(frozen=True)
class GroundEstimate:
  z: float | None
  source: str
  reason: str


def ground_height(model, distance, y_rel, height):
  if not all(math.isfinite(v) for v in (distance, y_rel, height)) or not 0 < distance <= 200 or not .5 <= height <= 3:
    return GroundEstimate(None, 'none', 'ground_input')
  forward = distance + RADAR_OFFSET
  path = model.get('position', {})
  xs, zs = path.get('x', []), path.get('z', [])
  if (len(xs) == len(zs) and len(xs) >= 2 and np.isfinite([*xs, *zs]).all() and
      np.all(np.diff(xs) > 0) and xs[0] <= forward <= xs[-1]):
    return GroundEstimate(float(np.interp(forward, xs, zs)) + height, 'path', 'candidate')

  lanes = model.get('laneLines', [])
  probs, stds = model.get('laneLineProbs', []), model.get('laneLineStds', [])
  if len(lanes) != 4 or len(probs) != 4 or len(stds) != 4:
    return GroundEstimate(None, 'none', 'lane_missing')
  bounds = []
  for i in (1, 2):
    probability, std = probs[i], stds[i]
    if not math.isfinite(probability) or not .8 <= probability <= 1 or not math.isfinite(std) or not 0 <= std <= .5:
      return GroundEstimate(None, 'none', 'lane_uncertain')
    line = lanes[i]
    x, y, z = (line.get(name, []) for name in ('x', 'y', 'z'))
    if (not 2 <= len(x) == len(y) == len(z) or not np.isfinite([*x, *y, *z]).all() or
        np.any(np.diff(x) <= 0)):
      return GroundEstimate(None, 'none', 'lane_geometry')
    if not x[0] <= forward <= x[-1]:
      return GroundEstimate(None, 'none', 'lane_range')
    j = min(max(int(np.searchsorted(x, forward)), 1), len(x) - 1)
    if abs((z[j] - z[j-1]) / (x[j] - x[j-1])) > .15:
      return GroundEstimate(None, 'none', 'lane_grade')
    bounds.append((float(np.interp(forward, x, y)), float(np.interp(forward, x, z))))
  (left_y, left_z), (right_y, right_z) = bounds
  # Model y is right-positive; radar/marker y_rel is left-positive.
  if not 2.5 <= right_y - left_y <= 5 or not left_y <= -y_rel <= right_y:
    return GroundEstimate(None, 'none', 'lane_bracket')
  if abs(left_z - right_z) > .25:
    return GroundEstimate(None, 'none', 'lane_height_disagreement')
  z = left_z + (-y_rel - left_y) / (right_y - left_y) * (right_z - left_z)
  return GroundEstimate(z, 'lanes', 'candidate')  # already ground z; no +height
