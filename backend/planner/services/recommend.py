"""Route ranking, following the assessment's preference order.

1. Fewest Severe miles   2. Fewest High miles   3. Lowest average risk
4. Shortest travel time

"No Travel" miles are ranked *ahead* of Severe miles: the table puts No Travel
above Severe, so a route that crosses a No Travel zone must never beat one
that only touches Severe weather.

Comparisons use small tolerances so that forecast noise (e.g. 0.2 mi of
Severe weather or a 0.004 difference in average risk) cannot override a
meaningfully faster route.
"""

from __future__ import annotations

from dataclasses import dataclass

MILES_TOLERANCE = 1.0
AVG_RISK_TOLERANCE = 0.02


@dataclass(frozen=True)
class RouteScore:
    route_id: str
    no_travel_miles: float
    severe_miles: float
    high_miles: float
    avg_risk: float
    trip_s: float


CRITERIA = (
    ("no_travel_miles", MILES_TOLERANCE, "fewer No Travel miles"),
    ("severe_miles", MILES_TOLERANCE, "fewer Severe miles"),
    ("high_miles", MILES_TOLERANCE, "fewer High miles"),
    ("avg_risk", AVG_RISK_TOLERANCE, "lower average risk"),
    ("trip_s", 0.0, "shorter travel time"),
)


def _deciding(a: RouteScore, b: RouteScore) -> tuple[int, str]:
    """(-1 if ``a`` is better, 1 if worse, 0 if tied) and the deciding criterion."""
    for attr, tolerance, label in CRITERIA:
        va, vb = getattr(a, attr), getattr(b, attr)
        if abs(va - vb) > tolerance:
            return (-1 if va < vb else 1), label
    return 0, "tied on every criterion"


def rank(scores: list[RouteScore]) -> list[RouteScore]:
    """Best first. Insertion sort with the tolerant comparator keeps ties stable."""
    ordered: list[RouteScore] = []
    for score in scores:
        pos = len(ordered)
        for i, other in enumerate(ordered):
            if _deciding(score, other)[0] < 0:
                pos = i
                break
        ordered.insert(pos, score)
    return ordered


def explain(best: RouteScore, others: list[RouteScore]) -> list[str]:
    """One plain-language reason per runner-up."""
    reasons = []
    for other in others:
        verdict, label = _deciding(best, other)
        if verdict == 0:
            reasons.append(f"Route {best.route_id} and Route {other.route_id} are equivalent; kept the first.")
            continue
        detail = _detail(best, other, label)
        reasons.append(f"Beats Route {other.route_id} on {label}{detail}.")
    return reasons


def _detail(best: RouteScore, other: RouteScore, label: str) -> str:
    if "No Travel" in label:
        return f" ({best.no_travel_miles:.0f} vs {other.no_travel_miles:.0f} mi)"
    if "Severe" in label:
        return f" ({best.severe_miles:.0f} vs {other.severe_miles:.0f} mi)"
    if "High" in label:
        return f" ({best.high_miles:.0f} vs {other.high_miles:.0f} mi)"
    if "average" in label:
        return f" ({best.avg_risk:.2f} vs {other.avg_risk:.2f})"
    minutes = (other.trip_s - best.trip_s) / 60
    return f" ({minutes:.0f} min faster)" if minutes < 90 else f" ({minutes / 60:.1f} h faster)"
