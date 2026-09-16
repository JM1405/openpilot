"""Bounded, map-only bend candidates for the B1 observer, never certified safe speeds.

Measure one directed link at a time. Do not turn a graph join or an unresolved
fork into a curve. Native vertices must support the whole measurement window;
resampling is for spacing independence, not a substitute for missing map data.
"""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from functools import lru_cache
import math


@dataclass(frozen=True)
class CurveLimits:
  # Development assumptions; no bank, grade, tire/friction or vehicle calibration.
  lateral_accel: float = 1.5  # m/s^2, v = sqrt(a_lat / abs(curvature))
  step: float = 5.0
  window: float = 20.0  # each side of the center; also exclude link boundaries
  max_gap: float = 25.0  # maximum original segment in a candidate's support
  min_radius: float = 20.0
  max_radius: float = 700.0
  min_turn: float = 12.0  # degrees, sustained change rather than one vertex
  min_span: float = 20.0
  max_vertex_turn: float = 25.0
  max_length: float = 10000.0
  max_points: int = 2048


LIMITS = CurveLimits()


@dataclass(frozen=True)
class Bend:
  start_m: float
  end_m: float
  curvature: float  # signed 1/m; peak magnitude over this bend
  target_speed: float  # m/s


@dataclass(frozen=True)
class CurveResult:
  bends: tuple[Bend, ...] = ()
  rejections: tuple[str, ...] = ()


def curvature(a, b, c):
  """Signed inverse circumradius from three metric points, including straight lines."""
  ab, bc, ac = math.dist(a, b), math.dist(b, c), math.dist(a, c)
  if min(ab, bc, ac) < .001:
    return 0.
  cross = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
  return 2 * cross / (ab * bc * ac)


def intersects(a, b, c, d):
  def side(p, q, r):
    return (q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0])
  # Bounding boxes are checked by the caller. Also reject collinear overlaps/touches.
  return side(a, b, c)*side(a, b, d) <= 0 and side(c, d, a)*side(c, d, b) <= 0


def self_crosses(points):
  boxes = sorted((min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1]), i)
                 for i, (a, b) in enumerate(zip(points, points[1:])))
  active = []
  for lo, hi, bottom, top, i in boxes:
    active = [box for box in active if box[1] >= lo]
    for _, _, other_bottom, other_top, j in active:
      if abs(i-j) > 1 and other_bottom <= top and bottom <= other_top:
        if intersects(points[i], points[i+1], points[j], points[j+1]):
          return True
    active.append((lo, hi, bottom, top, i))
  return False


@lru_cache(maxsize=128)
def analyze(points: tuple[tuple[float, float], ...]) -> CurveResult:
  """Geometry-only cache. Dates, direction, road match and GPS TTL are never cached here."""
  from .offline import xy, distance  # offline's helpers exist before this function runs
  limits = LIMITS
  def rejected(reason):
    return CurveResult(rejections=(reason,))
  if not 3 <= len(points) <= limits.max_points:
    return rejected('insufficientPoints' if len(points) < 3 else 'tooManyPoints')
  if any(len(p) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in p)
         or not -180 <= p[0] <= 180 or not -80 <= p[1] <= 80 for p in points):
    return rejected('invalidCoordinates')
  metric = tuple(xy(*p, points[0]) for p in points)
  # Stations use the same segment distances as the road matcher/event adapter.
  lengths = [distance(a, b) for a, b in zip(points, points[1:])]
  if min(lengths) < .001:
    return rejected('duplicatePoints')
  stations = [0.]
  for length in lengths:
    stations.append(stations[-1]+length)
  total = stations[-1]
  if total > limits.max_length:
    return rejected('geometryTooLong')
  if self_crosses(metric):
    return rejected('selfIntersection')
  # Inspect native vertex angles before interpolation can spread a kink into a bend.
  turns = []
  for a, b, c in zip(metric, metric[1:], metric[2:]):
    ab, bc = (b[0]-a[0], b[1]-a[1]), (c[0]-b[0], c[1]-b[1])
    turns.append(math.atan2(ab[0]*bc[1]-ab[1]*bc[0], ab[0]*bc[0]+ab[1]*bc[1]))
  if any(abs(t) > math.radians(limits.max_vertex_turn) for t in turns):
    return rejected('sharpVertex')
  native_curvatures = tuple(abs(curvature(a, b, c)) for a, b, c in zip(metric, metric[1:], metric[2:]))
  if total < 4 * limits.window + limits.min_span:
    return rejected('insufficientLength')

  def at(station):
    j = min(len(lengths)-1, bisect_right(stations, station)-1)
    fraction = (station-stations[j])/lengths[j]
    a, b = metric[j], metric[j+1]
    return (a[0]+fraction*(b[0]-a[0]), a[1]+fraction*(b[1]-a[1]))
  samples = [at(i*limits.step) for i in range(int(total/limits.step)+1)]
  width = round(limits.window/limits.step)
  measured = [(i*limits.step, curvature(samples[i-width], samples[i], samples[i+width]),
               curvature(samples[i-width//2], samples[i], samples[i+width//2]))
              for i in range(width, len(samples)-width)]
  groups, group = [], []
  for value in measured:
    if abs(value[1]) < 1/limits.max_radius:
      if group: groups.append(group); group = []
    else:
      if group and group[-1][1]*value[1] < 0:
        groups.append(group); group = []
      group.append(value)
  if group: groups.append(group)

  bends, reasons = [], set()
  for group in groups:
    start, end = group[0][0]-limits.window, group[-1][0]+limits.window
    # A bend reaching the available geometry edge may continue around a node/fork.
    if start < limits.window or end > total-limits.window:
      reasons.add('linkBoundary'); continue
    left, right = max(0, bisect_right(stations, start)-1), bisect_left(stations, end)
    if any(gap > limits.max_gap for gap in lengths[left:right]):
      reasons.add('sparseGeometry'); continue
    if group[-1][0]-group[0][0] < limits.min_span:
      reasons.add('shortBend'); continue
    # Two spatial scales must agree at the curvature peak. This rejects isolated
    # coordinate noise without averaging away a genuine tighter turn.
    peak = max(group, key=lambda value: max(abs(value[1]), abs(value[2])))
    k = max(abs(value) for row in group for value in row[1:])
    # Preserve the tighter native radius of a short smooth bend. Broad windows
    # alone can average its curvature down and overestimate its target speed.
    native_peak = max(native_curvatures[left:max(left, right-1)], default=0.)
    if native_peak > 1.5*k:
      reasons.add('inconsistentCurvature'); continue
    k = max(k, native_peak)
    if k > 1/limits.min_radius:
      reasons.add('radiusTooSmall'); continue
    if peak[1]*peak[2] <= 0 or not .65 <= abs(peak[2]/peak[1]) <= 1.5:
      reasons.add('inconsistentCurvature'); continue
    native_turns = turns[left:max(left, right-1)]
    total_turn = sum(abs(value) for value in native_turns)
    if (sum(abs(value) >= 1e-6 for value in native_turns) < 3
        or total_turn < math.radians(limits.min_turn)
        or abs(sum(native_turns)) < .85 * total_turn
        or max((abs(value) for value in native_turns), default=0.) > .45 * total_turn):
      reasons.add('unsupportedBend'); continue
    bends.append(Bend(start, end, math.copysign(k, peak[1]), math.sqrt(limits.lateral_accel/k)))
  return CurveResult(tuple(bends), tuple(sorted(reasons)))
