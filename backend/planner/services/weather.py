"""Hourly forecasts from Open-Meteo, cached per ~7-mile grid cell.

Every requested point is snapped to a 0.1° cell. Each cell's full 14-day
hourly series is cached, so the three routes and the heatmap (which overlap
heavily) share forecasts, and repeat plans make no upstream calls at all.
Cache misses are fetched in multi-location batches.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from . import geo
from .http import UpstreamError, get_json

CELL_DEG = 0.1
FORECAST_DAYS = 14
BATCH_SIZE = 100
CACHE_TTL_S = 30 * 60
HOURLY_VARS = ("wind_speed_10m", "wind_gusts_10m", "rain", "showers", "snowfall", "temperature_2m", "weather_code")


@dataclass(frozen=True)
class Conditions:
    wind_mph: float
    gust_mph: float
    rain_in_hr: float  # liquid rain incl. showers, over the hour ending at the sample
    snow_in_hr: float  # snowfall depth over the hour ending at the sample
    temp_f: float | None
    weather_code: int | None


@dataclass(frozen=True)
class HourlySeries:
    start_ts: int  # unix seconds of the first hourly value
    wind: tuple[float, ...]
    gust: tuple[float, ...]
    rain: tuple[float, ...]
    snow: tuple[float, ...]
    temp: tuple[float | None, ...]
    code: tuple[int | None, ...]

    @property
    def end_ts(self) -> int:
        return self.start_ts + (len(self.wind) - 1) * 3600

    def at(self, ts: float) -> Conditions | None:
        """Conditions at ``ts``, or ``None`` if outside the forecast window.

        Wind is linearly interpolated between hours. Precipitation is an hourly
        accumulation over the *preceding* hour, so we use the bucket that
        contains ``ts`` (the next whole hour).
        """
        if ts < self.start_ts or ts > self.end_ts:
            return None
        idx = (ts - self.start_ts) / 3600
        lo = int(math.floor(idx))
        hi = min(lo + 1, len(self.wind) - 1)
        t = idx - lo
        bucket = int(math.ceil(idx))
        return Conditions(
            wind_mph=self.wind[lo] + t * (self.wind[hi] - self.wind[lo]),
            gust_mph=self.gust[lo] + t * (self.gust[hi] - self.gust[lo]),
            rain_in_hr=self.rain[bucket],
            snow_in_hr=self.snow[bucket],
            temp_f=self.temp[lo],
            weather_code=self.code[bucket],
        )


def cell_of(point: geo.LonLat) -> tuple[int, int]:
    lon, lat = point
    return round(lon / CELL_DEG), round(lat / CELL_DEG)


def _cell_center(cell: tuple[int, int]) -> geo.LonLat:
    return cell[0] * CELL_DEG, cell[1] * CELL_DEG


def _cache_key(cell: tuple[int, int]) -> str:
    return f"wx:v1:{cell[0]}:{cell[1]}"


def _num(values: Iterable[float | None]) -> tuple[float, ...]:
    return tuple(0.0 if v is None else float(v) for v in values)


def _parse(item: dict) -> HourlySeries:
    h = item["hourly"]
    rain = tuple(r + s for r, s in zip(_num(h["rain"]), _num(h["showers"])))
    return HourlySeries(
        start_ts=int(h["time"][0]),
        wind=_num(h["wind_speed_10m"]),
        gust=_num(h["wind_gusts_10m"]),
        rain=rain,
        snow=_num(h["snowfall"]),
        temp=tuple(h["temperature_2m"]),
        code=tuple(h["weather_code"]),
    )


def _fetch(cells: list[tuple[int, int]]) -> dict[tuple[int, int], HourlySeries]:
    centers = [_cell_center(c) for c in cells]
    params = {
        "latitude": ",".join(f"{lat:.2f}" for _, lat in centers),
        "longitude": ",".join(f"{lon:.2f}" for lon, _ in centers),
        "hourly": ",".join(HOURLY_VARS),
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "temperature_unit": "fahrenheit",
        "timeformat": "unixtime",
        "timezone": "GMT",
        "forecast_days": FORECAST_DAYS,
    }
    url = settings.OPEN_METEO_URL
    if settings.OPEN_METEO_API_KEY:
        url = url.replace("api.open-meteo.com", "customer-api.open-meteo.com")
        params["apikey"] = settings.OPEN_METEO_API_KEY
    data = get_json(url, params, timeout=40)
    if isinstance(data, dict) and data.get("error"):
        raise UpstreamError(f"Weather provider error: {data.get('reason', 'unknown')}")
    items = data if isinstance(data, list) else [data]
    if len(items) != len(cells):
        raise UpstreamError("Weather provider returned an unexpected number of locations.")
    return {cell: _parse(item) for cell, item in zip(cells, items)}


def forecasts(points: Iterable[geo.LonLat]) -> dict[tuple[int, int], HourlySeries]:
    """Hourly series for every grid cell touched by ``points``."""
    cells = list(dict.fromkeys(cell_of(p) for p in points))
    found = cache.get_many([_cache_key(c) for c in cells])
    result = {c: found[_cache_key(c)] for c in cells if _cache_key(c) in found}
    missing = [c for c in cells if c not in result]
    for start in range(0, len(missing), BATCH_SIZE):
        fetched = _fetch(missing[start : start + BATCH_SIZE])
        cache.set_many({_cache_key(c): s for c, s in fetched.items()}, CACHE_TTL_S)
        result.update(fetched)
    return result
