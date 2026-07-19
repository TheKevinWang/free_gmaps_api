from __future__ import annotations

from urllib.parse import urlencode, urlunparse

_MAPS_BASE = "www.google.com"
_MAX_URL_LEN = 2048


def _check_length(url: str) -> str:
    if len(url) > _MAX_URL_LEN:
        raise ValueError(f"Maps URL exceeds {_MAX_URL_LEN} characters: {len(url)}")
    return url


def build_street_view_url(
    viewpoint: str | None,
    heading: float | None = None,
    pitch: float | None = None,
    fov: float | None = None,
    pano: str | None = None,
) -> str:
    params: dict[str, str] = {
        "api": "1",
        "map_action": "pano",
    }
    if viewpoint is not None:
        params["viewpoint"] = viewpoint
    if viewpoint is None and pano is None:
        raise ValueError("Street View URL requires a viewpoint or panorama ID.")
    if heading is not None:
        params["heading"] = str(heading)
    if pitch is not None:
        params["pitch"] = str(pitch)
    if fov is not None:
        params["fov"] = str(fov)
    if pano is not None:
        params["pano"] = pano
    qs = urlencode(params)
    url = urlunparse(("https", _MAPS_BASE, "/maps/@", "", qs, ""))
    return _check_length(url)
