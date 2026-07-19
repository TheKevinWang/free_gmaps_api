from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from free_gmaps_api.maps_urls.directions import build_directions_url
from free_gmaps_api.maps_urls.map_view import build_map_view_url
from free_gmaps_api.maps_urls.search import build_search_url
from free_gmaps_api.maps_urls.street_view import build_street_view_url


def _parse(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_search_url_has_api1() -> None:
    url = build_search_url("Space Needle Seattle WA")
    assert "api=1" in url
    qs = _parse(url)
    assert qs["api"] == ["1"]
    assert qs["query"] == ["Space Needle Seattle WA"]


def test_search_url_with_place_id() -> None:
    url = build_search_url("Space Needle", place_id="ChIJ123")
    qs = _parse(url)
    assert qs["query_place_id"] == ["ChIJ123"]


def test_directions_url_has_api1() -> None:
    url = build_directions_url("Space Needle Seattle WA", "Pike Place Market Seattle WA")
    assert "api=1" in url
    qs = _parse(url)
    assert qs["api"] == ["1"]
    assert "travelmode" in qs


def test_directions_url_bicycling() -> None:
    url = build_directions_url(
        "Space Needle Seattle WA",
        "Pike Place Market Seattle WA",
        travel_mode="bicycling",
    )
    qs = _parse(url)
    assert qs["travelmode"] == ["bicycling"]


def test_directions_url_waypoints_pipe_encoded() -> None:
    url = build_directions_url(
        "Seattle WA",
        "Portland OR",
        waypoints=["Olympia WA", "Tacoma WA"],
    )
    assert "waypoints" in url
    qs = _parse(url)
    waypoints_val = qs["waypoints"][0]
    assert "Olympia WA" in waypoints_val
    assert "|" in waypoints_val


def test_directions_url_avoid_ferries() -> None:
    url = build_directions_url("A", "B", avoid=["ferries", "tolls"])
    qs = _parse(url)
    avoid_val = qs["avoid"][0]
    assert "ferries" in avoid_val
    assert "tolls" in avoid_val


def test_directions_url_unsupported_avoid_ignored() -> None:
    url = build_directions_url("A", "B", avoid=["unknown_flag"])
    qs = _parse(url)
    assert "avoid" not in qs


def test_street_view_url_pano() -> None:
    url = build_street_view_url(viewpoint="48.8584,2.2945", heading=210.0, pitch=0.0, fov=80.0)
    assert "api=1" in url
    assert "map_action=pano" in url
    qs = _parse(url)
    assert qs["viewpoint"] == ["48.8584,2.2945"]
    assert qs["heading"] == ["210.0"]


def test_street_view_url_with_pano_param() -> None:
    url = build_street_view_url(viewpoint="48.8584,2.2945", pano="ABCD1234")
    qs = _parse(url)
    assert qs["pano"] == ["ABCD1234"]


def test_street_view_url_allows_exact_pano_without_viewpoint() -> None:
    url = build_street_view_url(viewpoint=None, pano="ABCD1234")
    qs = _parse(url)
    assert qs["pano"] == ["ABCD1234"]
    assert "viewpoint" not in qs


def test_street_view_url_requires_viewpoint_or_pano() -> None:
    with pytest.raises(ValueError, match="viewpoint or panorama"):
        build_street_view_url(viewpoint=None)


def test_map_view_url_has_api1() -> None:
    url = build_map_view_url(center="47.6062,-122.3321", zoom=12)
    assert "api=1" in url
    assert "map_action=map" in url
    qs = _parse(url)
    assert qs["zoom"] == ["12"]


def test_map_view_url_satellite_transit() -> None:
    url = build_map_view_url(
        center="47.6062,-122.3321",
        zoom=12,
        basemap="satellite",
        layer="transit",
    )
    qs = _parse(url)
    assert qs["basemap"] == ["satellite"]
    assert qs["layer"] == ["transit"]


def test_map_view_url_unsupported_basemap_ignored() -> None:
    url = build_map_view_url(center="47.6062,-122.3321", basemap="custom_basemap")
    qs = _parse(url)
    assert "basemap" not in qs


def test_url_length_limit_search() -> None:
    long_query = "A" * 2100
    with pytest.raises(ValueError, match="2048"):
        build_search_url(long_query)


def test_url_length_limit_directions() -> None:
    many_waypoints = [
        f"Waypoint number {i} in some very long city name somewhere" for i in range(80)
    ]
    with pytest.raises(ValueError, match="2048"):
        build_directions_url("Origin City USA", "Destination City USA", waypoints=many_waypoints)
