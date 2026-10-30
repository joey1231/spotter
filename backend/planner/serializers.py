from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

MAX_DEPARTURE_AHEAD = timedelta(days=10)
MAX_ROUTE_POINTS = 2000


class PlaceSerializer(serializers.Serializer):
    """A place is either picked from search (label + coordinates) or free text."""

    label = serializers.CharField(max_length=200, required=False, allow_blank=True)
    lat = serializers.FloatField(min_value=-90, max_value=90, required=False)
    lon = serializers.FloatField(min_value=-180, max_value=180, required=False)

    def validate(self, attrs):
        has_coords = "lat" in attrs and "lon" in attrs
        if not has_coords and not attrs.get("label", "").strip():
            raise serializers.ValidationError("Enter a place name or pick one from the list.")
        return attrs


def _validate_departure(value):
    now = timezone.now()
    if value < now - timedelta(hours=1):
        raise serializers.ValidationError("Departure cannot be in the past.")
    if value > now + MAX_DEPARTURE_AHEAD:
        raise serializers.ValidationError("Departure must be within 10 days (forecast horizon).")
    return value


class PlanRequestSerializer(serializers.Serializer):
    origin = PlaceSerializer()
    destination = PlaceSerializer()
    departure = serializers.DateTimeField(validators=[_validate_departure])
    load_lb = serializers.FloatField(min_value=0, max_value=200_000)
    interval_mi = serializers.ChoiceField(choices=[10, 25, 50], default=25)
    apply_hos = serializers.BooleanField(default=True)


class CoordinateListField(serializers.ListField):
    child = serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=2)


class HeatmapRequestSerializer(serializers.Serializer):
    routes = serializers.ListField(
        child=CoordinateListField(min_length=2, max_length=MAX_ROUTE_POINTS), min_length=1, max_length=3
    )
    departure = serializers.DateTimeField(validators=[_validate_departure])
    load_lb = serializers.FloatField(min_value=0, max_value=200_000)
