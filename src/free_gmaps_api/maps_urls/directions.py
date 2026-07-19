from __future__ import annotations

from urllib.parse import urlencode, urlunparse

_MAPS_BASE = "www.google.com"
_MAX_URL_LEN = 2048
_SUPPORTED_AVOID = {"ferries", "highways", "tolls"}
_SUPPORTED_MODES = {"driving", "walking", "bicycling", "transit"}


def _check_length(url: str) -> str:
    if len(url) > _MAX_URL_LEN:
        raise ValueError(f"Maps URL exceeds {_MAX_URL_LEN} characters: {len(url)}")
    return url


def build_directions_url(
    origin: str,
    destination: str,
    travel_mode: str = "driving",
    waypoints: list[str] | None = None,
    avoid: list[str] | None = None,
) -> str:
    mode = travel_mode.lower()
    if mode not in _SUPPORTED_MODES:
        mode = "driving"
    params: dict[str, str] = {
        "api": "1",
        "origin": origin,
        "destination": destination,
        "travelmode": mode,
    }
    if waypoints:
        params["waypoints"] = "|".join(waypoints)
    if avoid:
        supported = [a for a in avoid if a.lower() in _SUPPORTED_AVOID]
        if supported:
            params["avoid"] = "|".join(supported)
    qs = urlencode(params)
    url = urlunparse(("https", _MAPS_BASE, "/maps/dir/", "", qs, ""))
    return _check_length(url)
