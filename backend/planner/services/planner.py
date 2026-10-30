"""Trip planning: routes → timed checkpoints → weather → risk → recommendation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from . import geo, hos, recommend, routing, weather
from .risk import Assessment, RiskLevel, assess

HEATMAP_HOURS = 48
ROUTE_IDS = "ABC"
DISPLAY_SIMPLIFY_DEG = 0.0004  # ~40 m: invisible at route zoom, shrinks payload ~5x


@dataclass(frozen=True)
class TripRequest:
    origin: geo.LonLat
    destination: geo.LonLat
    departure: datetime
    load_lb: float
    interval_mi: int
    apply_hos: bool


@dataclass
class Checkpoint:
    mile: float
    point: geo.LonLat
    drive_s: float
    eta_ts: float
    span: tuple[float, float]  # the stretch of road this checkpoint represents
    conditions: weather.Conditions | None
    risk: Assessment | None

    @property
    def span_miles(self) -> float:
        return self.span[1] - self.span[0]


def checkpoint_miles(total_mi: float, interval_mi: float) -> list[float]:
    """Origin, then every ``interval_mi`` miles, then the destination."""
    miles = [0.0]
    m = interval_mi
    while m < total_mi - interval_mi * 0.25:  # avoid a near-duplicate stop just before arrival
        miles.append(m)
        m += interval_mi
    miles.append(total_mi)
    return miles


def spans(miles: list[float]) -> list[tuple[float, float]]:
    """Each checkpoint owns the road nearer to it than to its neighbours."""
    edges = [miles[0], *((a + b) / 2 for a, b in zip(miles, miles[1:])), miles[-1]]
    return list(zip(edges, edges[1:]))


def _round_pt(p: geo.LonLat) -> list[float]:
    return [round(p[0], 5), round(p[1], 5)]


def _build_checkpoints(route: routing.Route, req: TripRequest) -> list[Checkpoint]:
    depart_ts = req.departure.timestamp()
    miles = checkpoint_miles(route.distance_mi, req.interval_mi)
    out = []
    for mile, span in zip(miles, spans(miles)):
        drive_s = route.drive_s_at_mile(mile)
        out.append(
            Checkpoint(
                mile=mile,
                point=geo.point_at_mile(route.coords, route.cum_miles, mile),
                drive_s=drive_s,
                eta_ts=depart_ts + hos.elapsed_for_drive(drive_s, req.apply_hos),
                span=span,
                conditions=None,
                risk=None,
            )
        )
    return out


def _attach_weather(all_checkpoints: list[Checkpoint], load_lb: float) -> None:
    series = weather.forecasts(cp.point for cp in all_checkpoints)
    for cp in all_checkpoints:
        cp.conditions = series[weather.cell_of(cp.point)].at(cp.eta_ts)
        if cp.conditions:
            c = cp.conditions
            cp.risk = assess(c.wind_mph, c.rain_in_hr, c.snow_in_hr, load_lb)


def _metrics(checkpoints: list[Checkpoint]) -> dict:
    by_level = {level.key: 0.0 for level in RiskLevel}
    unknown = 0.0
    weighted = 0.0
    for cp in checkpoints:
        if cp.risk is None:
            unknown += cp.span_miles
            continue
        by_level[cp.risk.level.key] += cp.span_miles
        weighted += cp.risk.level * cp.span_miles
    known = sum(by_level.values())
    return {
        "miles_by_level": {k: round(v, 1) for k, v in by_level.items()},
        "unknown_miles": round(unknown, 1),
        "avg_risk": round(weighted / known, 3) if known else 0.0,
        "max_level": max((cp.risk.level for cp in checkpoints if cp.risk), default=RiskLevel.LOW).key,
    }


def _risk_segments(route: routing.Route, checkpoints: list[Checkpoint]) -> list[dict]:
    """Route geometry split into runs of equal risk, for colouring the line."""
    runs: list[dict] = []
    for cp in checkpoints:
        level = cp.risk.level.key if cp.risk else "unknown"
        if runs and runs[-1]["level"] == level:
            runs[-1]["end"] = cp.span[1]
        else:
            runs.append({"level": level, "start": cp.span[0], "end": cp.span[1]})
    segments = []
    for run in runs:
        coords = geo.slice_by_miles(route.coords, route.cum_miles, run["start"], run["end"])
        coords = geo.simplify(coords, DISPLAY_SIMPLIFY_DEG)
        segments.append({"level": run["level"], "coordinates": [_round_pt(p) for p in coords]})
    return segments


def _hourly_positions(route: routing.Route, req: TripRequest) -> list[list[float]]:
    """Where the truck is at departure + 0…48 h (parked during HOS stops)."""
    positions = []
    for h in range(HEATMAP_HOURS + 1):
        drive_s = hos.drive_for_elapsed(h * 3600, req.apply_hos)
        mile = route.mile_at_drive_s(min(drive_s, route.drive_s))
        positions.append(_round_pt(geo.point_at_mile(route.coords, route.cum_miles, mile)))
    return positions


def _serialize_checkpoint(cp: Checkpoint) -> dict:
    c, r = cp.conditions, cp.risk
    return {
        "mile": round(cp.mile, 1),
        "coordinates": _round_pt(cp.point),
        "eta": datetime.fromtimestamp(cp.eta_ts, tz=timezone.utc).isoformat(),
        "eta_ts": int(cp.eta_ts),
        "drive_s": int(cp.drive_s),
        "span_miles": round(cp.span_miles, 1),
        "weather": None
        if c is None
        else {
            "wind_mph": round(c.wind_mph, 1),
            "gust_mph": round(c.gust_mph, 1),
            "rain_in_hr": round(c.rain_in_hr, 3),
            "snow_in_hr": round(c.snow_in_hr, 3),
            "temp_f": None if c.temp_f is None else round(c.temp_f),
            "weather_code": c.weather_code,
        },
        "risk": None
        if r is None
        else {
            "level": r.level.key,
            "score": round(r.score, 2),
            "wind": r.wind_level.key,
            "rain": r.rain_level.key,
            "snow": r.snow_level.key,
            "drivers": list(r.drivers),
            "load_escalated": r.load_escalated,
        },
    }


def plan_trip(req: TripRequest) -> dict:
    routes = routing.find_routes(req.origin, req.destination)
    checkpoints = [_build_checkpoints(route, req) for route in routes]
    _attach_weather([cp for cps in checkpoints for cp in cps], req.load_lb)

    depart_ts = req.departure.timestamp()
    results, scores = [], []
    for route_id, route, cps in zip(ROUTE_IDS, routes, checkpoints):
        metrics = _metrics(cps)
        trip_s = hos.elapsed_for_drive(route.drive_s, req.apply_hos)
        miles = metrics["miles_by_level"]
        scores.append(
            recommend.RouteScore(
                route_id=route_id,
                no_travel_miles=miles["no_travel"],
                severe_miles=miles["severe"],
                high_miles=miles["high"],
                avg_risk=metrics["avg_risk"],
                trip_s=trip_s,
            )
        )
        results.append(
            {
                "id": route_id,
                "roads": route.roads,
                "distance_mi": round(route.distance_mi, 1),
                "drive_s": int(route.drive_s),
                "trip_s": int(trip_s),
                "stop_s": int(trip_s - route.drive_s),
                "arrival": datetime.fromtimestamp(depart_ts + trip_s, tz=timezone.utc).isoformat(),
                "arrival_ts": int(depart_ts + trip_s),
                **metrics,
                "geometry": [_round_pt(p) for p in geo.simplify(route.coords, DISPLAY_SIMPLIFY_DEG)],
                "segments": _risk_segments(route, cps),
                "checkpoints": [_serialize_checkpoint(cp) for cp in cps],
                "hourly_positions": _hourly_positions(route, req),
            }
        )

    ranking = recommend.rank(scores)
    best = ranking[0]
    for result in results:
        result["rank"] = next(i for i, s in enumerate(ranking) if s.route_id == result["id"]) + 1

    warnings = []
    if len(routes) < routing.ROUTE_COUNT:
        warnings.append(f"Only {len(routes)} distinct route(s) exist between these points.")
    if any(r["unknown_miles"] for r in results):
        warnings.append("Part of the trip is beyond the 14-day forecast window; those miles are unscored.")
    if best.no_travel_miles:
        warnings.append("Every route crosses No Travel conditions. Consider delaying departure.")

    return {
        "departure": req.departure.isoformat(),
        "departure_ts": int(depart_ts),
        "load_lb": req.load_lb,
        "interval_mi": req.interval_mi,
        "apply_hos": req.apply_hos,
        "routes": results,
        "recommendation": {
            "route_id": best.route_id,
            "ranking": [s.route_id for s in ranking],
            "reasons": recommend.explain(best, ranking[1:]),
        },
        "warnings": warnings,
    }
