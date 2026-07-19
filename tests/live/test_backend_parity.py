from __future__ import annotations

import os

import pytest

from free_gmaps_api.contracts.requests import DirectionsRequest, GeocodeRequest, PlaceSearchRequest
from free_gmaps_api.settings import Settings
from tests.helpers.backends import build_test_backend

pytestmark = pytest.mark.live
_ENABLED = os.environ.get("GMAPS_LIVE") == "1" and os.environ.get("GMAPS_LIVE_HTTP") == "1"


async def test_live_backends_agree_on_durable_space_needle_semantics() -> None:
    if not _ENABLED:
        pytest.skip("Set both GMAPS_LIVE=1 and GMAPS_LIVE_HTTP=1 for backend parity.")
    http = build_test_backend(
        Settings(backend="http", artifact_dir=".free-gmaps-api/artifacts/parity-http")
    )
    browser = build_test_backend(
        Settings(backend="zendriver", artifact_dir=".free-gmaps-api/artifacts/parity-browser")
    )
    try:
        geocode_request = GeocodeRequest(address="Space Needle Seattle WA")
        place_request = PlaceSearchRequest(query="Space Needle Seattle WA")
        http_geocode = await http.geocode(geocode_request)
        browser_geocode = await browser.geocode(geocode_request)
        http_place = await http.place_search(place_request)
        browser_place = await browser.place_search(place_request)
    finally:
        await http.close()
        await browser.close()

    assert http_geocode.ok is True
    assert browser_geocode.ok is True
    assert http_geocode.extracted.coordinates is not None
    assert browser_geocode.extracted.coordinates is not None
    assert abs(http_geocode.extracted.coordinates.lat - 47.6205063) <= 0.01
    assert abs(http_geocode.extracted.coordinates.lng - -122.3492774) <= 0.01
    assert abs(browser_geocode.extracted.coordinates.lat - 47.6205063) <= 0.01
    assert abs(browser_geocode.extracted.coordinates.lng - -122.3492774) <= 0.01
    assert http_place.ok is True
    assert browser_place.ok is True
    assert http_place.extracted.name is not None
    assert browser_place.extracted.name is not None
    assert {"space", "needle"} <= set(http_place.extracted.name.casefold().split())
    assert {"space", "needle"} <= set(browser_place.extracted.name.casefold().split())


async def test_live_backends_agree_on_directions_distance_and_duration() -> None:
    if not _ENABLED:
        pytest.skip("Set both GMAPS_LIVE=1 and GMAPS_LIVE_HTTP=1 for backend parity.")
    http = build_test_backend(
        Settings(backend="http", artifact_dir=".free-gmaps-api/artifacts/parity-http")
    )
    browser = build_test_backend(
        Settings(backend="zendriver", artifact_dir=".free-gmaps-api/artifacts/parity-browser")
    )
    request = DirectionsRequest(
        origin="Space Needle Seattle WA",
        destination="Pike Place Market Seattle WA",
    )
    try:
        http_directions = await http.directions(request)
        browser_directions = await browser.directions(request)
    finally:
        await http.close()
        await browser.close()

    assert http_directions.ok is True
    assert browser_directions.ok is True
    assert http_directions.extracted.selected_route is not None
    assert browser_directions.extracted.selected_route is not None
    assert http_directions.extracted.selected_route.distance_text
    assert http_directions.extracted.selected_route.duration_text
    assert browser_directions.extracted.selected_route.distance_text
    assert browser_directions.extracted.selected_route.duration_text
    assert http_directions.extracted.selected_route.distance_meters_approximate is not None
    assert browser_directions.extracted.selected_route.distance_meters_approximate is not None
    assert http_directions.extracted.selected_route.duration_seconds_approximate is not None
    assert browser_directions.extracted.selected_route.duration_seconds_approximate is not None
    assert (
        abs(
            http_directions.extracted.selected_route.distance_meters_approximate
            - browser_directions.extracted.selected_route.distance_meters_approximate
        )
        <= 500
    )
    assert (
        abs(
            http_directions.extracted.selected_route.duration_seconds_approximate
            - browser_directions.extracted.selected_route.duration_seconds_approximate
        )
        <= 300
    )
