"""Weather heatmap grid covering the trip corridor for departure + 0…48 h.

The grid is regular in Web-Mercator (square cells on screen), aligned to a
global lattice so repeated requests hit the same weather cache cells, and
masked to a buffer around the routes. Cell size grows with trip length to
keep the number of forecast points (and upstream calls) bounded.
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np

from . import geo, weather
from .risk import RAIN_IN_HR, SNOW_IN_HR, wind_risk

HOURS = 48
MAX_POINTS = 350
CELL_SIZES_DEG = (0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.65, 0.8, 1.0, 1.25, 1.5)
METRICS = ("risk", "wind", "rain", "snow")


def corridor_half_width_mi(longest_route_mi: float) -> float:
    return min(60.0, max(25.0, longest_route_mi * 0.05))


def build_grid(routes: list[list[geo.LonLat]]) -> tuple[list[geo.LonLat], float]:
    """Grid points inside the corridor, and the cell size (degrees of longitude)."""
    simplified = [geo.simplify(r, 0.01) for r in routes]
    longest = max(geo.cumulative_miles(r)[-1] for r in routes)
    half_width = corridor_half_width_mi(longest)

    all_pts = np.asarray([p for r in simplified for p in r])
    mid_lat = float(np.mean(all_pts[:, 1]))
    lat_scale = math.cos(math.radians(mid_lat))
    pad_lat = half_width / 69.0
    pad_lon = pad_lat / max(lat_scale, 0.2)
    min_lon, min_lat = all_pts.min(axis=0) - (pad_lon, pad_lat)
    max_lon, max_lat = all_pts.max(axis=0) + (pad_lon, pad_lat)

    points: list[geo.LonLat] = []
    for cell in CELL_SIZES_DEG:
        dlon, dlat = cell, cell * lat_scale
        lons = np.arange(math.floor(min_lon / dlon), math.ceil(max_lon / dlon) + 1) * dlon
        lats = np.arange(math.floor(min_lat / dlat), math.ceil(max_lat / dlat) + 1) * dlat
        grid = np.array(np.meshgrid(lons, lats)).reshape(2, -1).T
        # Cheap bbox pre-filter before the exact distance test.
        if len(grid) > MAX_POINTS * 40:
            continue
        dist = np.min([geo.distance_to_polyline_mi(grid, line) for line in simplified], axis=0)
        inside = grid[dist <= half_width]
        if len(inside) <= MAX_POINTS:
            points = [(round(float(lon), 4), round(float(lat), 4)) for lon, lat in inside]
            return points, cell
    return points, CELL_SIZES_DEG[-1]


def build_heatmap(routes: list[list[geo.LonLat]], departure: datetime, load_lb: float) -> dict:
    points, cell = build_grid(routes)
    series = weather.forecasts(points)
    start = departure.timestamp()
    hours = [int(start + h * 3600) for h in range(HOURS + 1)]

    values: dict[str, list[list[float | None]]] = {m: [] for m in METRICS}
    for point in points:
        s = series[weather.cell_of(point)]
        rows: dict[str, list[float | None]] = {m: [] for m in METRICS}
        for ts in hours:
            c = s.at(ts)
            if c is None:
                for m in METRICS:
                    rows[m].append(None)
                continue
            _, wind_score, _ = wind_risk(c.wind_mph, load_lb)
            rain_score = RAIN_IN_HR.score(c.rain_in_hr)
            snow_score = SNOW_IN_HR.score(c.snow_in_hr)
            rows["wind"].append(round(wind_score, 2))
            rows["rain"].append(round(rain_score, 2))
            rows["snow"].append(round(snow_score, 2))
            rows["risk"].append(round(max(wind_score, rain_score, snow_score), 2))
        for m in METRICS:
            values[m].append(rows[m])

    return {"hours": hours, "cell_deg": cell, "points": [list(p) for p in points], "values": values}
