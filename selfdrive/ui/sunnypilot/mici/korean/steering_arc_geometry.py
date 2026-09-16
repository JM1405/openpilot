"""Pinned MICI rounded arc geometry, isolated from native GUI initialization.

Copied from mici/onroad/torque_bar.py at b67898fac4e9; only the inactive DEBUG
branches are omitted. Keep the original quantization, point order and caps.
"""

import math
from functools import wraps
from collections import OrderedDict
import numpy as np


def quantized_lru_cache(maxsize=128):

  def decorator(func):
    cache = OrderedDict()

    @wraps(func)
    def wrapper(r_mid, thickness, a0_deg, a1_deg, **kwargs):
      key = (round(r_mid), round(thickness), round(a0_deg * 10) / 10, round(a1_deg * 10) / 10, tuple(sorted(kwargs.items())))
      if key in cache:
        cache.move_to_end(key)
      else:
        if len(cache) >= maxsize:
          cache.popitem(last=False)
        result = func(r_mid, thickness, a0_deg, a1_deg, **kwargs)
        cache[key] = result
      return cache[key]

    return wrapper

  return decorator


@quantized_lru_cache(maxsize=256)
def arc_bar_pts(
  r_mid: float, thickness: float, a0_deg: float, a1_deg: float, *, max_points: int = 100, cap_segs: int = 10, cap_radius: float = 7, px_per_seg: float = 2.0
) -> np.ndarray:
  """Return Nx2 np.float32 points for a single closed polygon (rounded thick arc), centered at origin."""

  def get_cap(left: bool, a_deg: float):
    nx, ny = (math.cos(math.radians(a_deg)), math.sin(math.radians(a_deg)))
    tx, ty = (-ny, nx)
    mx, my = (nx * r_mid, ny * r_mid)
    ex = mx + nx * (half - cap_radius)
    ey = my + ny * (half - cap_radius)
    if not left:
      alpha = np.deg2rad(np.linspace(90, 0, cap_segs + 2))[1:-1]
    else:
      alpha = np.deg2rad(np.linspace(180, 90, cap_segs + 2))[1:-1]
    cap_end = np.c_[
      ex + np.cos(alpha) * cap_radius * tx + np.sin(alpha) * cap_radius * nx, ey + np.cos(alpha) * cap_radius * ty + np.sin(alpha) * cap_radius * ny
    ]
    ex2 = mx + nx * (-half + cap_radius)
    ey2 = my + ny * (-half + cap_radius)
    if not left:
      alpha2 = np.deg2rad(np.linspace(0, -90, cap_segs + 1))[:-1]
    else:
      alpha2 = np.deg2rad(np.linspace(90 - 90 - 90, 0 - 90 - 90, cap_segs + 1))[:-1]
    cap_end_bot = np.c_[
      ex2 + np.cos(alpha2) * cap_radius * tx + np.sin(alpha2) * cap_radius * nx, ey2 + np.cos(alpha2) * cap_radius * ty + np.sin(alpha2) * cap_radius * ny
    ]
    if not left:
      cap_end = np.vstack((cap_end, cap_end_bot))
    else:
      cap_end = np.vstack((cap_end_bot, cap_end))
    return cap_end

  if a1_deg < a0_deg:
    a0_deg, a1_deg = (a1_deg, a0_deg)
  half = thickness * 0.5
  cap_radius = min(cap_radius, half)
  span = max(0.001, a1_deg - a0_deg)
  arc_len = r_mid * math.radians(span)
  arc_segs = max(6, int(arc_len / px_per_seg))
  max_arc = (max_points - (4 * cap_segs + 3)) // 2
  arc_segs = max(6, min(arc_segs, max_arc))
  ang_o = np.deg2rad(np.linspace(a0_deg, a1_deg, arc_segs + 1))
  outer = np.c_[np.cos(ang_o) * (r_mid + half), np.sin(ang_o) * (r_mid + half)]
  cap_end = get_cap(False, a1_deg)
  ang_i = np.deg2rad(np.linspace(a1_deg, a0_deg, arc_segs + 1))
  inner = np.c_[np.cos(ang_i) * (r_mid - half), np.sin(ang_i) * (r_mid - half)]
  cap_start = get_cap(True, a0_deg)
  pts = np.vstack((outer, cap_end, inner, cap_start, outer[:1])).astype(np.float32)
  pts = np.roll(pts, cap_segs, axis=0)
  return pts
