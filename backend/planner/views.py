import logging

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .serializers import HeatmapRequestSerializer, PlanRequestSerializer
from .services import corridor, geocoding
from .services.http import UpstreamError
from .services.planner import TripRequest, plan_trip

log = logging.getLogger(__name__)


def _upstream_failure(exc: UpstreamError) -> Response:
    log.warning("Upstream failure: %s", exc)
    return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)


def _resolve_place(place: dict) -> tuple[tuple[float, float], str]:
    if "lat" in place and "lon" in place:
        return (place["lon"], place["lat"]), place.get("label") or f"{place['lat']:.4f}, {place['lon']:.4f}"
    found = geocoding.resolve(place["label"])
    return (found["lon"], found["lat"]), found["label"]


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET"])
def geocode(request):
    try:
        return Response({"results": geocoding.search(request.query_params.get("q", ""))})
    except UpstreamError as exc:
        return _upstream_failure(exc)


@api_view(["POST"])
def plan(request):
    serializer = PlanRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
        origin, origin_label = _resolve_place(data["origin"])
        destination, destination_label = _resolve_place(data["destination"])
        result = plan_trip(
            TripRequest(
                origin=origin,
                destination=destination,
                departure=data["departure"],
                load_lb=data["load_lb"],
                interval_mi=data["interval_mi"],
                apply_hos=data["apply_hos"],
            )
        )
    except UpstreamError as exc:
        return _upstream_failure(exc)
    result["origin"] = {"label": origin_label, "coordinates": list(origin)}
    result["destination"] = {"label": destination_label, "coordinates": list(destination)}
    return Response(result)


@api_view(["POST"])
def heatmap(request):
    serializer = HeatmapRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    routes = [[tuple(p) for p in route] for route in data["routes"]]
    try:
        return Response(corridor.build_heatmap(routes, data["departure"], data["load_lb"]))
    except UpstreamError as exc:
        return _upstream_failure(exc)
