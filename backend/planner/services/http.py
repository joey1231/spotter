"""Shared HTTP session for third-party providers."""

from __future__ import annotations

from functools import lru_cache

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class UpstreamError(Exception):
    """A third-party provider failed or returned an unusable response."""


@lru_cache(maxsize=1)
def session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=0.6, status_forcelist=(429, 502, 503, 504), allowed_methods=("GET",))
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=16)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers["User-Agent"] = settings.HTTP_USER_AGENT
    return s


def get_json(url: str, params: dict, timeout: float = 25) -> object:
    try:
        resp = session().get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise UpstreamError(f"Could not reach {url}: {exc}") from exc
    if resp.status_code == 429:
        raise UpstreamError("Upstream rate limit reached, please retry in a minute.")
    try:
        data = resp.json()
    except ValueError as exc:
        raise UpstreamError(f"Unexpected response from {url} (HTTP {resp.status_code})") from exc
    return data
