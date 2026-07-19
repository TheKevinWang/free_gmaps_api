from __future__ import annotations

from urllib.parse import urlencode, urlunparse

_MAPS_BASE = "www.google.com"
_MAX_URL_LEN = 2048
_SUPPORTED_BASEMAPS = {"roadmap", "satellite", "terrain"}
_SUPPORTED_LAYERS = {"traffic", "transit", "bicycling"}


def _check_length(url: str) -> str:
    if len(url) > _MAX_URL_LEN:
        raise ValueError(f"Maps URL exceeds {_MAX_URL_LEN} characters: {len(url)}")
    return url


def build_map_view_url(
    center: str,
    zoom: int | None = None,
    basemap: str | None = None,
    layer: str | None = None,
) -> str:
    params: dict[str, str] = {
        "api": "1",
        "map_action": "map",
        "center": center,
    }
    if zoom is not None:
        params["zoom"] = str(zoom)
    if basemap and basemap.lower() in _SUPPORTED_BASEMAPS:
        params["basemap"] = basemap.lower()
    if layer and layer.lower() in _SUPPORTED_LAYERS:
        params["layer"] = layer.lower()
    qs = urlencode(params)
    url = urlunparse(("https", _MAPS_BASE, "/maps/@", "", qs, ""))
    return _check_length(url)
