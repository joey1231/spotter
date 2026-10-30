"""Place search via Photon (OpenStreetMap data; permits type-ahead use)."""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.core.cache import cache

from .http import UpstreamError, get_json

CACHE_TTL_S = 24 * 3600


def _label(props: dict) -> str:
    parts = [props.get("name"), props.get("city"), props.get("state"), props.get("countrycode")]
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen)


def search(query: str, limit: int = 6) -> list[dict]:
    query = query.strip()
    if len(query) < 2:
        return []
    key = "geo:v1:" + hashlib.sha1(f"{query.lower()}|{limit}".encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = get_json(settings.PHOTON_URL, {"q": query, "limit": limit, "lang": "en"}, timeout=10)
    if not isinstance(data, dict) or "features" not in data:
        raise UpstreamError("Geocoding service returned an unexpected response.")
    results = []
    for feature in data["features"]:
        lon, lat = feature["geometry"]["coordinates"]
        label = _label(feature.get("properties", {}))
        if label:
            results.append({"label": label, "lon": lon, "lat": lat})
    cache.set(key, results, CACHE_TTL_S)
    return results


def resolve(query: str) -> dict:
    results = search(query, limit=1)
    if not results:
        raise UpstreamError(f"Could not find a location for '{query}'.")
    return results[0]
