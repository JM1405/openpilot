"""Bounded, original-coordinate route corridor for observation-only map matching.

A route never overrides uncertain current-road GPS. It may confirm a unique
future branch only when both map geometries agree in order and direction.
"""
import json
import math
from dataclasses import dataclass
from itertools import pairwise

from .offline import xy, distance, bearing, angle_delta

MAX_WINDOW = 1024


@dataclass(frozen=True)
class RouteHint:
  state: str = 'none'
  identity: str = ''
  points: tuple = ()
  valid_until: float = 0.
  reason: str = ''

  def wire(self):
    return json.dumps({'state': self.state, 'identity': self.identity, 'points': self.points,
                       'valid_until': self.valid_until, 'reason': self.reason}, separators=(',', ':'))

  @classmethod
  def parse(cls, raw, now):
    if not raw:
      return cls()
    if len(raw) > 56000:
      raise ValueError('routeHintTooLarge')
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {'state', 'identity', 'points', 'valid_until', 'reason'}:
      raise ValueError('invalidRouteHint')
    if data['state'] not in ('none', 'pending', 'active') or not isinstance(data['identity'], str) or len(data['identity']) > 128 or not isinstance(data['reason'], str) or len(data['reason']) > 128:
      raise ValueError('invalidRouteHint')
    points, until = data['points'], data['valid_until']
    if not isinstance(points, list) or len(points) > MAX_WINDOW or type(until) not in (float, int) or not math.isfinite(until):
      raise ValueError('invalidRouteHint')
    for p in points:
      if not isinstance(p, list) or len(p) != 2 or any(type(v) not in (float, int) or not math.isfinite(v) for v in p) or abs(p[0]) > 180 or abs(p[1]) > 85:
        raise ValueError('invalidRouteHint')
    if data['state'] == 'active':
      if not data['identity'] or len(points) < 2 or not now < until <= now + 3.01:
        raise ValueError('staleRouteHint')
    elif points or until != 0:
      raise ValueError('invalidRouteHint')
    return cls(data['state'], data['identity'], tuple(tuple(p) for p in points), until, data['reason'])


class RouteShape:
  """Index once at complete upload. Unusable long segments cannot select a window."""
  CELL = .001

  def __init__(self, points):
    self.points = tuple(tuple(p) for p in points)
    self.grid = {}
    self.along = [0.]
    entries = 0
    for i, (a, b) in enumerate(pairwise(self.points)):
      length = distance(a, b)
      self.along.append(self.along[-1]+length)
      # Do not build an unbounded geographic index from malformed/sparse edges.
      if length > 500 or max(abs(a[1]), abs(b[1])) > 85:
        continue
      x0, x1 = sorted((int(math.floor(a[0]/self.CELL)), int(math.floor(b[0]/self.CELL))))
      y0, y1 = sorted((int(math.floor(a[1]/self.CELL)), int(math.floor(b[1]/self.CELL))))
      for x in range(x0, x1+1):
        for y in range(y0, y1+1):
          self.grid.setdefault((x, y), []).append(i)
          entries += 1
          if entries > 500000:
            raise ValueError('routeIndexTooLarge')

  def window(self, fix):
    if fix is None or fix.bearing_deg is None:
      return (), 'routeLocationUnavailable'
    cell = (math.floor(fix.lon/self.CELL), math.floor(fix.lat/self.CELL))
    indices = set()
    for x in range(cell[0]-1, cell[0]+2):
      for y in range(cell[1]-1, cell[1]+2):
        indices.update(self.grid.get((x, y), ()))
    if len(indices) > 4096:
      return (), 'routeGeometryAmbiguous'
    rows = []
    for i in indices:
      a, b = self.points[i:i+2]
      dx, dy = xy(*b, a);px, py = xy(fix.lon, fix.lat, a)
      length = math.hypot(dx, dy)
      if length < .01:
        continue
      t = min(1., max(0., (px*dx+py*dy)/length**2))
      gap = math.hypot(px-t*dx, py-t*dy)
      if gap <= max(12., 2*fix.accuracy_m) and angle_delta(bearing(a,b),fix.bearing_deg) <= 35.:
        rows.append((gap, self.along[i]+t*length, i))
    if not rows:
      return (), 'routeLocationMismatch'
    rows.sort();gap, along, index = rows[0]
    if any(abs(at-along) > 25 and other <= gap+2*fix.accuracy_m+2 for other, at, _ in rows[1:]):
      return (), 'routeGeometryAmbiguous'
    start = max(0,index-1)
    end = index+2
    while end < len(self.points) and end-start < MAX_WINDOW and self.along[end-1]-along < 1100:
      end += 1
    points = self.points[start:end]
    if any(distance(a,b)>100 for a,b in pairwise(points)):
      return (), 'routeGeometrySparse'
    return points, ''


class RouteCorridor:
  def __init__(self, points, fix):
    self.origin = (fix.lon, fix.lat)
    local = [xy(*p, self.origin) for p in points]
    self.segments = [];total = 0.
    for (ax,ay),(bx,by) in pairwise(local):
      dx,dy = bx-ax,by-ay;length=math.hypot(dx,dy)
      if length < .01:
        continue
      if length > 100:
        raise ValueError('routeGeometrySparse')
      self.segments.append((ax,ay,dx,dy,length,total,math.degrees(math.atan2(dx,dy))%360))
      total += length
    gap, along, course, ambiguous = self.project((0.,0.))
    if not self.segments or ambiguous or gap > max(12.,2*fix.accuracy_m) or angle_delta(course,fix.bearing_deg)>35:
      raise ValueError('routeLocationMismatch')
    self.start = along
    self.horizon = min(1000., max(0., total-along-10.))

  def project(self, point):
    px,py=point;best=(math.inf,0.,0.);rows=[]
    for ax,ay,dx,dy,length,at,course in self.segments:
      t=min(1.,max(0.,((px-ax)*dx+(py-ay)*dy)/length**2))
      gap=math.hypot(px-ax-t*dx,py-ay-t*dy)
      row=(gap,at+t*length,course);rows.append(row)
      if gap<best[0]:best=row
    ambiguous=any(gap<=best[0]+2. and abs(at-best[1])>25 for gap,at,_ in rows)
    return (*best,ambiguous)

  def supports(self, link, start, end):
    if end-start < 2:
      return False
    travelled=0.;last=None;checked=0
    for a,b in pairwise(link.points):
      length=distance(a,b)
      if length<.01:continue
      lo=max(start,travelled);hi=min(end,travelled+length)
      if hi>lo:
        course=bearing(a,b)
        for i in range(max(1,math.ceil((hi-lo)/10.))+1):
          at=lo+(hi-lo)*i/max(1,math.ceil((hi-lo)/10.));t=(at-travelled)/length
          point=(a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t)
          gap,route_at,direction,ambiguous=self.project(xy(*point,self.origin))
          if ambiguous or gap>8. or angle_delta(course,direction)>25 or (last is not None and route_at<last-1.):
            return False
          if last is not None and route_at-last>25.:
            return False
          last=route_at;checked+=1
      travelled+=length
      if travelled>=end:break
    return checked>=2 and travelled>=end-1.
