"""Weather risk classification — a direct encoding of the assessment's rule table.

Boundary semantics (the source table overlaps at shared edges, e.g. rain
"0.10–0.25" and "0.25–0.50"):

* Every band is lower-inclusive, so a value sitting on a shared edge is placed
  in the *more* severe band (0.25 in/hr rain → High). For a safety tool,
  rounding toward caution is the defensible choice.
* The "No Travel" edge follows the table literally: wind is ``≥ 55 mph``, while
  rain and snow are strictly ``> 1.00`` and ``> 3.0`` in/hr.

Load rules escalate wind risk for heavy trucks (higher centre of mass and
rollover risk) and never lower a level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return self.name.replace("_", " ").title()

    @property
    def key(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Thresholds:
    """Lower edges of Moderate, High, Severe and No Travel."""

    edges: tuple[float, float, float, float]
    no_travel_inclusive: bool

    def level(self, value: float) -> RiskLevel:
        moderate, high, severe, no_travel = self.edges
        if value > no_travel or (self.no_travel_inclusive and value >= no_travel):
            return RiskLevel.NO_TRAVEL
        if value >= severe:
            return RiskLevel.SEVERE
        if value >= high:
            return RiskLevel.HIGH
        if value >= moderate:
            return RiskLevel.MODERATE
        return RiskLevel.LOW

    def score(self, value: float) -> float:
        """Continuous 0–4 score whose integer part equals ``level(value)``.

        Used only for smooth heatmap shading; ranking uses discrete levels.
        """
        level = self.level(value)
        if level is RiskLevel.NO_TRAVEL:
            return 4.0
        lower = 0.0 if level is RiskLevel.LOW else self.edges[level - 1]
        upper = self.edges[level]
        return level + min(0.999, max(0.0, (value - lower) / (upper - lower)))


WIND_MPH = Thresholds((25, 35, 45, 55), no_travel_inclusive=True)
RAIN_IN_HR = Thresholds((0.10, 0.25, 0.50, 1.00), no_travel_inclusive=False)
SNOW_IN_HR = Thresholds((0.5, 1.0, 2.0, 3.0), no_travel_inclusive=False)

# Load rules: (wind band, load must exceed this many lb, resulting level).
HEAVY_LOAD_WIND_RULES: tuple[tuple[RiskLevel, float, RiskLevel], ...] = (
    (RiskLevel.SEVERE, 30_000, RiskLevel.NO_TRAVEL),  # 45–54 mph + >30,000 lb
    (RiskLevel.HIGH, 40_000, RiskLevel.SEVERE),  # 35–44 mph + >40,000 lb
)


@dataclass(frozen=True)
class Assessment:
    level: RiskLevel
    score: float
    wind_level: RiskLevel
    rain_level: RiskLevel
    snow_level: RiskLevel
    wind_score: float
    rain_score: float
    snow_score: float
    load_escalated: bool = False
    drivers: tuple[str, ...] = field(default=())


def wind_risk(wind_mph: float, load_lb: float) -> tuple[RiskLevel, float, bool]:
    """Wind level and score after applying the heavy-load escalation rules."""
    level = WIND_MPH.level(wind_mph)
    score = WIND_MPH.score(wind_mph)
    for band, min_load, escalated in HEAVY_LOAD_WIND_RULES:
        if level is band and load_lb > min_load:
            score = 4.0 if escalated is RiskLevel.NO_TRAVEL else escalated + (score - level)
            return escalated, score, True
    return level, score, False


def assess(wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_lb: float) -> Assessment:
    """Overall checkpoint risk is the worst of the three conditions."""
    wind_level, wind_score, escalated = wind_risk(wind_mph, load_lb)
    rain_level, rain_score = RAIN_IN_HR.level(rain_in_hr), RAIN_IN_HR.score(rain_in_hr)
    snow_level, snow_score = SNOW_IN_HR.level(snow_in_hr), SNOW_IN_HR.score(snow_in_hr)

    level = max(wind_level, rain_level, snow_level)
    drivers: tuple[str, ...] = ()
    if level > RiskLevel.LOW:
        drivers = tuple(
            name
            for name, lvl in (("wind", wind_level), ("rain", rain_level), ("snow", snow_level))
            if lvl == level
        )
    return Assessment(
        level=level,
        score=max(wind_score, rain_score, snow_score),
        wind_level=wind_level,
        rain_level=rain_level,
        snow_level=snow_level,
        wind_score=wind_score,
        rain_score=rain_score,
        snow_score=snow_score,
        load_escalated=escalated and wind_level == level,
        drivers=drivers,
    )
