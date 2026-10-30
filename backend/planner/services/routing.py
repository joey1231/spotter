"""Route generation on top of OSRM.

OSRM's ``alternatives`` frequently returns fewer than three routes on long
trips, so when that happens we synthesise more by forcing the route through
via-points offset to either side of the fastest route. Candidates are kept only
if they are meaningfully different (low overlap with routes already chosen),
not absurdly slow, and free of out-and-back spurs.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from . import geo
from .http import UpstreamError, get_json

log = logging.getLogger(__name__)

ROUTE_COUNT = 3
MAX_SLOWDOWN = 1.45  # reject alternatives more than 45% slower than the fastest
MAX_OVERLAP = 0.80  # reject alternatives sharing >80% of their length with a kept route
VIA_POSITIONS = (0.5, 0.35, 0.65)  # fraction along the fastest route
VIA_OFFSETS = (0.12, 0.22)  # perpendicular offset as a fraction of straight-line distance
CACHE_TTL_S = 15 * 60


@dataclass
class Route:
    coords: list[geo.LonLat]
    cum_miles: list[float]  # distance from origin at every vertex
    cum_drive_s: list[float]  # truck driving time from origin at every vertex
    roads: list[str]  # main roads, most-used first

    @property
    def distance_mi(self) -> float:
        return self.cum_miles[-1]

    @property
    def drive_s(self) -> float:
        return self.cum_drive_s[-1]

    def drive_s_at_mile(self, mile: float) -> float:
        return geo.interpolate(self.cum_miles, self.cum_drive_s, mile)

    def mile_at_drive_s(self, drive_s: float) -> float:
        return geo.interpolate(self.cum_drive_s, self.cum_miles, drive_s)


def _osrm(points: list[geo.LonLat], alternatives: int = 0) -> list[dict]:
    coords = ";".join(f"{lon:.5f},{lat:.5f}" for lon, lat in points)
    key = f"osrm:v1:{coords}:{alternatives}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    params = {
        "overview": "full",
        "geometries": "geojson",
        "annotations": "distance,duration",
        "steps": "true",
        "alternatives": str(alternatives) if alternatives else "false",
        "continue_straight": "true",  # no U-turns at via-points
    }
    data = get_json(f"{settings.OSRM_BASE_URL}/route/v1/driving/{coords}", params)
    if not isinstance(data, dict) or data.get("code") != "Ok":
        message = data.get("message") if isinstance(data, dict) else None
        raise UpstreamError(message or "No drivable route found between these locations.")
    routes = data["routes"]
    cache.set(key, routes, CACHE_TTL_S)
    return routes


def _build_route(raw: dict) -> Route:
    coords = [tuple(c) for c in raw["geometry"]["coordinates"]]
    # Drop consecutive duplicates (OSRM repeats the shared vertex between legs).
    coords = [c for i, c in enumerate(coords) if i == 0 or c != coords[i - 1]]
    cum_miles = geo.cumulative_miles(coords)

    seg_durations = [d for leg in raw["legs"] for d in leg["annotation"]["duration"]]
    seg_distances = [d for leg in raw["legs"] for d in leg["annotation"]["distance"]]
    pairs = [(dur, dist) for dur, dist in zip(seg_durations, seg_distances) if dist > 0]

    # OSRM's car profile is too fast for a loaded truck: cap every segment at
    # the truck's maximum speed.
    max_mps = settings.TRUCK_MAX_SPEED_MPH * geo.METERS_PER_MILE / 3600
    truck = [max(dur, dist / max_mps) for dur, dist in pairs]

    if len(truck) == len(coords) - 1:
        cum_drive = [0.0]
        for d in truck:
            cum_drive.append(cum_drive[-1] + d)
    else:
        # Geometry and annotations disagree (rare); spread time by distance.
        total = sum(truck) or raw["duration"]
        cum_drive = [total * m / cum_miles[-1] for m in cum_miles] if cum_miles[-1] else [0.0] * len(coords)

    # Summarise by the most-driven roads, preferring numbered highways (I 80)
    # over street names, which is how drivers describe a route.
    road_miles: dict[tuple[bool, str], float] = defaultdict(float)
    for leg in raw["legs"]:
        for step in leg.get("steps", []):
            ref = (step.get("ref") or "").split(";")[0].strip()
            name = ref or (step.get("name") or "").strip()
            if name:
                road_miles[(bool(ref), name)] += step["distance"] / geo.METERS_PER_MILE
    ranked = sorted(road_miles.items(), key=lambda kv: (not kv[0][0], -kv[1]))
    roads = [name for (_, name), _ in ranked[:3]]

    return Route(coords=coords, cum_miles=cum_miles, cum_drive_s=cum_drive, roads=roads)


def _via_points(base: Route, origin: geo.LonLat, dest: geo.LonLat) -> list[geo.LonLat]:
    """Candidate via-points to either side of the fastest route, best first."""
    span = geo.haversine_mi(origin, dest)
    mid_lat = math.radians((origin[1] + dest[1]) / 2)
    # Unit vector origin→dest in a locally-scaled lon/lat plane, and its normal.
    dx = (dest[0] - origin[0]) * math.cos(mid_lat)
    dy = dest[1] - origin[1]
    norm = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / norm, dx / norm
    miles_per_deg = geo.EARTH_RADIUS_MI * math.pi / 180

    vias = []
    for offset in VIA_OFFSETS:
        for position in VIA_POSITIONS:
            lon, lat = geo.point_at_mile(base.coords, base.cum_miles, base.distance_mi * position)
            shift_deg = offset * span / miles_per_deg
            for side in (1, -1):
                vias.append((lon + side * nx * shift_deg / math.cos(mid_lat), lat + side * ny * shift_deg))
    return vias


def _has_spur(route: Route, tolerance_mi: float = 0.2, min_run_mi: int = 3) -> bool:
    """Detect out-and-back detours: the route re-drives a stretch it already covered.

    Requires a run of several consecutive 1-mile samples on top of earlier road,
    so tight switchbacks that merely pass close to themselves are not flagged.
    """
    samples = geo.resample(route.coords, 1.0)
    run = 0
    for i in range(4, len(samples)):
        near = geo.distance_to_polyline_mi([samples[i]], samples[: i - 3])[0] < tolerance_mi
        run = run + 1 if near else 0
        if run >= min_run_mi:
            return True
    return False


def _is_distinct(candidate: Route, kept: list[Route]) -> bool:
    return all(geo.overlap_fraction(candidate.coords, other.coords) <= MAX_OVERLAP for other in kept)


def find_routes(origin: geo.LonLat, dest: geo.LonLat) -> list[Route]:
    """Up to three distinct truck routes, fastest first."""
    if geo.haversine_mi(origin, dest) < 1:
        raise UpstreamError("Origin and destination are too close together.")

    kept: list[Route] = []
    for raw in _osrm([origin, dest], alternatives=ROUTE_COUNT):
        route = _build_route(raw)
        if not kept or _is_distinct(route, kept):
            kept.append(route)
    fastest = min(r.drive_s for r in kept)

    if len(kept) < ROUTE_COUNT:
        vias = _via_points(kept[0], origin, dest)
        with ThreadPoolExecutor(max_workers=3) as pool:
            # Small batches keep us polite with the public OSRM server and let us
            # stop early once we have enough routes.
            for start in range(0, len(vias), 3):
                batch = vias[start : start + 3]
                results = [r for r in pool.map(lambda via: _try_via(origin, via, dest), batch) if r]
                # Most different first, so a batch contributes its best alternative.
                results.sort(key=lambda r: max(geo.overlap_fraction(r.coords, k.coords) for k in kept))
                for route in results:
                    if route.drive_s > fastest * MAX_SLOWDOWN:
                        continue
                    if _is_distinct(route, kept) and not _has_spur(route):
                        kept.append(route)
                    if len(kept) == ROUTE_COUNT:
                        break
                if len(kept) == ROUTE_COUNT:
                    break

    kept.sort(key=lambda r: r.drive_s)
    return kept


def _try_via(origin: geo.LonLat, via: geo.LonLat, dest: geo.LonLat) -> Route | None:
    try:
        return _build_route(_osrm([origin, via, dest])[0])
    except UpstreamError as exc:
        log.info("Via-point candidate %s rejected: %s", via, exc)
        return None
