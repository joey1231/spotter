"""Small, dependency-light geometry helpers.

Coordinates are always ``(lon, lat)`` in degrees, matching GeoJSON. Distances
are in miles unless a name says otherwise.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Sequence

import numpy as np

EARTH_RADIUS_MI = 3958.7613
METERS_PER_MILE = 1609.344

LonLat = tuple[float, float]


def haversine_mi(a: LonLat, b: LonLat) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(min(1.0, h)))


def cumulative_miles(coords: Sequence[LonLat]) -> list[float]:
    """Running distance from the first vertex to each vertex."""
    out = [0.0]
    for prev, cur in zip(coords, coords[1:]):
        out.append(out[-1] + haversine_mi(prev, cur))
    return out


def interpolate(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    """Piecewise-linear lookup of ``y`` at ``x``; ``xs`` must be non-decreasing."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_right(xs, x) - 1
    span = xs[i + 1] - xs[i]
    t = 0.0 if span == 0 else (x - xs[i]) / span
    return ys[i] + t * (ys[i + 1] - ys[i])


def point_at_mile(coords: Sequence[LonLat], cum: Sequence[float], mile: float) -> LonLat:
    """Point located ``mile`` miles along the polyline (clamped to its ends)."""
    if mile <= 0:
        return coords[0]
    if mile >= cum[-1]:
        return coords[-1]
    i = bisect_right(cum, mile) - 1
    span = cum[i + 1] - cum[i]
    t = 0.0 if span == 0 else (mile - cum[i]) / span
    (x0, y0), (x1, y1) = coords[i], coords[i + 1]
    return (x0 + t * (x1 - x0), y0 + t * (y1 - y0))


def slice_by_miles(coords: Sequence[LonLat], cum: Sequence[float], start: float, end: float) -> list[LonLat]:
    """Sub-polyline between two mile markers, with interpolated end points."""
    i0 = bisect_right(cum, start)
    i1 = bisect_right(cum, end)
    return [point_at_mile(coords, cum, start), *coords[i0:i1], point_at_mile(coords, cum, end)]


def simplify(coords: Sequence[LonLat], tolerance_deg: float) -> list[LonLat]:
    """Douglas-Peucker simplification (iterative, so long routes cannot overflow the stack)."""
    n = len(coords)
    if n < 3:
        return list(coords)
    pts = np.asarray(coords, dtype=float)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi - lo < 2:
            continue
        seg = pts[lo + 1 : hi]
        a, b = pts[lo], pts[hi]
        ab = b - a
        denom = float(ab @ ab)
        if denom == 0:
            d = np.hypot(*(seg - a).T)
        else:
            t = np.clip(((seg - a) @ ab) / denom, 0, 1)
            d = np.hypot(*(seg - (a + t[:, None] * ab)).T)
        idx = int(np.argmax(d))
        if d[idx] > tolerance_deg:
            mid = lo + 1 + idx
            keep[mid] = True
            stack.extend(((lo, mid), (mid, hi)))
    return [tuple(p) for p in pts[keep].tolist()]


def _to_local_miles(points: np.ndarray, ref_lat: float) -> np.ndarray:
    """Equirectangular projection; accurate enough for corridor-scale distances."""
    deg = EARTH_RADIUS_MI * math.pi / 180
    return np.column_stack((points[:, 0] * deg * math.cos(math.radians(ref_lat)), points[:, 1] * deg))


def distance_to_polyline_mi(points: Sequence[LonLat], line: Sequence[LonLat]) -> np.ndarray:
    """Distance from every point to the nearest segment of ``line`` (vectorised)."""
    p = np.asarray(points, dtype=float)
    l = np.asarray(line, dtype=float)
    ref_lat = float(np.mean(l[:, 1]))
    p = _to_local_miles(p, ref_lat)
    l = _to_local_miles(l, ref_lat)
    if len(l) == 1:
        return np.hypot(*(p - l[0]).T)
    a, b = l[:-1], l[1:]
    ab = b - a
    denom = np.einsum("ij,ij->i", ab, ab)
    denom[denom == 0] = 1e-12
    best = np.full(len(p), np.inf)
    # Chunk over points to bound memory (points x segments matrix).
    for start in range(0, len(p), 512):
        chunk = p[start : start + 512]
        ap = chunk[:, None, :] - a[None, :, :]
        t = np.clip(np.einsum("ijk,jk->ij", ap, ab) / denom, 0, 1)
        proj = a[None, :, :] + t[..., None] * ab[None, :, :]
        d = np.hypot(*(chunk[:, None, :] - proj).transpose(2, 0, 1))
        best[start : start + 512] = d.min(axis=1)
    return best


def resample(coords: Sequence[LonLat], step_mi: float) -> list[LonLat]:
    """Evenly spaced points along a polyline, including both ends."""
    cum = cumulative_miles(coords)
    total = cum[-1]
    count = max(1, int(total // step_mi))
    return [point_at_mile(coords, cum, total * i / count) for i in range(count + 1)]


def overlap_fraction(candidate: Sequence[LonLat], other: Sequence[LonLat], tolerance_mi: float = 1.0) -> float:
    """Share of ``candidate`` (by length) that runs within ``tolerance_mi`` of ``other``."""
    samples = resample(candidate, 3.0)
    near = distance_to_polyline_mi(samples, simplify(other, 0.002)) <= tolerance_mi
    return float(near.mean())
