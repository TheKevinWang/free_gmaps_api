from __future__ import annotations

from urllib.parse import urlencode, urlunparse

_MAPS_BASE = "www.google.com"
_MAX_URL_LEN = 2048


def _check_length(url: str) -> str:
    if len(url) > _MAX_URL_LEN:
        raise ValueError(f"Maps URL exceeds {_MAX_URL_LEN} characters: {len(url)}")
    return url


def build_search_url(query: str, place_id: str | None = None) -> str:
    params: dict[str, str] = {"api": "1", "query": query}
    if place_id:
        params["query_place_id"] = place_id
    qs = urlencode(params)
    url = urlunparse(("https", _MAPS_BASE, "/maps/search/", "", qs, ""))
    return _check_length(url)
