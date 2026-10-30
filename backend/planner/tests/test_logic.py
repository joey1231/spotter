from django.test import SimpleTestCase

from planner.services import geo, hos, recommend
from planner.services.planner import checkpoint_miles, spans
from planner.services.risk import RAIN_IN_HR, SNOW_IN_HR, WIND_MPH, RiskLevel, assess
from planner.services.weather import HourlySeries

L, M, H, S, NT = RiskLevel


class ThresholdTests(SimpleTestCase):
    def test_wind_bands(self):
        cases = [(0, L), (24.9, L), (25, M), (34.9, M), (35, H), (44.9, H), (45, S), (54.9, S), (55, NT), (80, NT)]
        for value, expected in cases:
            self.assertEqual(WIND_MPH.level(value), expected, value)

    def test_rain_bands_shared_edges_round_toward_caution(self):
        cases = [(0.09, L), (0.10, M), (0.25, H), (0.50, S), (1.00, S), (1.01, NT)]
        for value, expected in cases:
            self.assertEqual(RAIN_IN_HR.level(value), expected, value)

    def test_snow_bands(self):
        cases = [(0.4, L), (0.5, M), (1.0, H), (2.0, S), (3.0, S), (3.1, NT)]
        for value, expected in cases:
            self.assertEqual(SNOW_IN_HR.level(value), expected, value)

    def test_score_integer_part_matches_level(self):
        for t in (WIND_MPH, RAIN_IN_HR, SNOW_IN_HR):
            for i in range(0, 400):
                value = i * t.edges[-1] / 300
                self.assertEqual(int(t.score(value)), t.level(value), (t, value))


class LoadRuleTests(SimpleTestCase):
    def test_55_mph_is_no_travel_for_any_load(self):
        self.assertEqual(assess(55, 0, 0, 0).level, NT)

    def test_45_54_mph_over_30k_is_no_travel(self):
        self.assertEqual(assess(50, 0, 0, 30_000).level, S)  # boundary: must *exceed* 30,000
        result = assess(50, 0, 0, 30_001)
        self.assertEqual(result.level, NT)
        self.assertTrue(result.load_escalated)

    def test_35_44_mph_over_40k_is_severe(self):
        self.assertEqual(assess(40, 0, 0, 40_000).level, H)
        self.assertEqual(assess(40, 0, 0, 40_001).level, S)
        self.assertEqual(assess(40, 0, 0, 35_000).level, H)  # below the 40k rule, above 30k

    def test_load_does_not_change_light_wind(self):
        self.assertEqual(assess(30, 0, 0, 80_000).level, M)

    def test_overall_is_worst_condition_and_reports_drivers(self):
        result = assess(10, 0.3, 2.5, 10_000)
        self.assertEqual(result.level, S)
        self.assertEqual(result.drivers, ("snow",))


class HoursOfServiceTests(SimpleTestCase):
    def test_short_trip_has_no_stops(self):
        self.assertEqual(hos.elapsed_for_drive(5 * 3600), 5 * 3600)

    def test_break_after_eight_hours(self):
        self.assertEqual(hos.elapsed_for_drive(9 * 3600), 9.5 * 3600)

    def test_no_rest_when_arriving_exactly_at_eleven_hours(self):
        self.assertEqual(hos.elapsed_for_drive(11 * 3600), 11.5 * 3600)

    def test_ten_hour_rest_after_eleven_hours(self):
        self.assertEqual(hos.elapsed_for_drive(12 * 3600), (12 + 0.5 + 10) * 3600)

    def test_disabled(self):
        self.assertEqual(hos.elapsed_for_drive(30 * 3600, enabled=False), 30 * 3600)

    def test_inverse_round_trip(self):
        for minutes in range(0, 40 * 60, 7):
            drive = minutes * 60
            self.assertAlmostEqual(hos.drive_for_elapsed(hos.elapsed_for_drive(drive)), drive)

    def test_parked_during_rest(self):
        self.assertEqual(hos.drive_for_elapsed(15 * 3600), 11 * 3600)


def score(rid, nt=0.0, sev=0.0, high=0.0, avg=0.0, hours=10.0):
    return recommend.RouteScore(rid, nt, sev, high, avg, hours * 3600)


class RecommendationTests(SimpleTestCase):
    def ids(self, scores):
        return [s.route_id for s in recommend.rank(scores)]

    def test_priority_order(self):
        self.assertEqual(self.ids([score("A", sev=25), score("B", high=100, hours=12)]), ["B", "A"])
        self.assertEqual(self.ids([score("A", high=25), score("B", avg=1.5, hours=12)]), ["B", "A"])
        self.assertEqual(self.ids([score("A", avg=0.4), score("B", avg=0.1, hours=12)]), ["B", "A"])
        self.assertEqual(self.ids([score("A", hours=12), score("B", hours=11)]), ["B", "A"])

    def test_no_travel_outranks_severe(self):
        self.assertEqual(self.ids([score("A", nt=10), score("B", sev=500)]), ["B", "A"])

    def test_noise_in_average_risk_does_not_beat_faster_route(self):
        self.assertEqual(self.ids([score("A", avg=0.01, hours=10), score("B", avg=0.0, hours=12)]), ["A", "B"])

    def test_explanation_names_deciding_criterion(self):
        best, other = score("A", hours=10), score("B", high=25, hours=9)
        self.assertEqual(recommend.explain(best, [other]), ["Beats Route B on fewer High miles (0 vs 25 mi)."])


class CheckpointTests(SimpleTestCase):
    def test_checkpoints_cover_whole_route_exactly_once(self):
        miles = checkpoint_miles(103.0, 25)
        self.assertEqual(miles, [0, 25, 50, 75, 103.0])  # 100 is within a quarter-interval of arrival
        parts = spans(miles)
        self.assertAlmostEqual(sum(b - a for a, b in parts), 103.0)
        self.assertEqual(parts[0], (0, 12.5))

    def test_no_near_duplicate_before_destination(self):
        self.assertEqual(checkpoint_miles(52.0, 25), [0, 25, 52.0])

    def test_point_at_mile_interpolates(self):
        coords = [(0.0, 0.0), (0.0, 1.0)]
        cum = geo.cumulative_miles(coords)
        lon, lat = geo.point_at_mile(coords, cum, cum[-1] / 2)
        self.assertAlmostEqual(lat, 0.5)


class WeatherSamplingTests(SimpleTestCase):
    series = HourlySeries(
        start_ts=0,
        wind=(10.0, 20.0, 30.0),
        gust=(0.0, 0.0, 0.0),
        rain=(0.0, 0.2, 0.6),
        snow=(0.0, 0.0, 0.0),
        temp=(50, 50, 50),
        code=(0, 61, 63),
    )

    def test_wind_interpolates_and_precip_uses_hour_ending_after_eta(self):
        c = self.series.at(1800)
        self.assertAlmostEqual(c.wind_mph, 15.0)
        self.assertAlmostEqual(c.rain_in_hr, 0.2)

    def test_on_the_hour(self):
        self.assertAlmostEqual(self.series.at(3600).rain_in_hr, 0.2)

    def test_outside_window(self):
        self.assertIsNone(self.series.at(3 * 3600))
