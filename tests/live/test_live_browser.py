from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from free_gmaps_api.browser.session import BrowserSession
from free_gmaps_api.contracts.envelope import ApiEnvelope
from free_gmaps_api.contracts.requests import (
    DirectionsRequest,
    DistanceMatrixRequest,
    GeocodeRequest,
    MapViewRequest,
    PlaceDetailsRequest,
    PlaceSearchRequest,
    ReverseGeocodeRequest,
    StreetViewRequest,
    ViewportSize,
)
from free_gmaps_api.services.directions import run_directions
from free_gmaps_api.services.distance_matrix import run_distance_matrix
from free_gmaps_api.services.geocode import run_geocode, run_reverse_geocode
from free_gmaps_api.services.map_view import run_map_view
from free_gmaps_api.services.place import run_place_details, run_place_search
from free_gmaps_api.services.street_view import run_street_view
from free_gmaps_api.settings import Settings
from tests.helpers.assert_envelope import assert_envelope_shape

_LIVE = os.environ.get("GMAPS_LIVE") == "1"
pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
async def live_session() -> object:
    if not _LIVE:
        pytest.skip("Set GMAPS_LIVE=1 to run live browser tests.")
    settings = Settings(
        headless=True,
        trace=os.environ.get("GMAPS_TRACE") == "1",
        artifact_dir=".free-gmaps-api/artifacts/live",
    )
    session = BrowserSession(settings)
    yield session
    await session.stop()


@pytest.mark.live
async def test_live_street_view_clean_cincinnati_image(live_session: BrowserSession) -> None:
    request = StreetViewRequest(
        location="39.10176,-84.5121708",
        heading=45.0,
        pitch=0.0,
        fov=80.0,
        size="640x360",
        viewport=ViewportSize(width=1280, height=720),
    )
    response = await run_street_view(request, live_session)
    assert_envelope_shape(response)
    assert response.ok is True
    assert response.extracted.image is not None
    assert response.extracted.image.clean is True
    assert response.extracted.image.source == "web_renderer"
    assert response.extracted.image.width == 640
    assert response.extracted.image.height == 360
    assert response.extracted.image.content_type == "image/jpeg"
    clean_path = Path(response.extracted.image.path)
    assert clean_path.is_file()
    assert clean_path.read_bytes().startswith(b"\xff\xd8")
    assert response.extracted.screenshot is not None
    assert response.extracted.screenshot.path != ""
    assert response.artifacts.street_view_image == response.extracted.image.path
    assert response.artifacts.screenshot != response.artifacts.street_view_image
    _assert_diagnostic_artifacts(response)


@pytest.mark.live
async def test_live_geocode_space_needle(live_session: BrowserSession) -> None:
    request = GeocodeRequest(address="Space Needle Seattle WA")
    response = await run_geocode(request, live_session)
    assert_envelope_shape(response)
    assert response.ok is True
    assert response.extracted.coordinates is not None
    assert abs(response.extracted.coordinates.lat - 47.6205063) <= 0.01
    assert abs(response.extracted.coordinates.lng - -122.3492774) <= 0.01
    assert response.extracted.display_name is not None
    assert "space needle" in response.extracted.display_name.casefold()
    _assert_diagnostic_artifacts(response)


@pytest.mark.live
async def test_live_reverse_geocode_space_needle(live_session: BrowserSession) -> None:
    request = ReverseGeocodeRequest(latlng="47.6205063,-122.3492774")
    response = await run_reverse_geocode(request, live_session)
    assert_envelope_shape(response)
    assert response.ok is False
    assert response.extracted.input_coordinates == "47.6205063,-122.3492774"
    assert response.extracted.nearest_address_or_place is None
    assert "No address-bearing place record" in response.confidence.notes[0]
    _assert_diagnostic_artifacts(response)


@pytest.mark.live
async def test_live_directions_alternatives_and_steps(
    live_session: BrowserSession,
) -> None:
    request = DirectionsRequest(
        origin="Space Needle Seattle WA",
        destination="Pike Place Market Seattle WA",
        travel_mode="driving",
        alternatives=True,
    )
    response = await run_directions(request, live_session)
    assert_envelope_shape(response)
    assert response.ok is True
    assert len(response.extracted.routes) >= 2
    assert response.extracted.selected_route is not None
    assert response.extracted.selected_route.label is not None
    assert response.extracted.selected_route.duration_seconds_approximate is not None
    assert response.extracted.selected_route.distance_meters_approximate is not None
    if not response.extracted.selected_route.steps:
        assert "No route steps parsed" in " ".join(response.confidence.notes)
    for value in (
        response.artifacts.interaction_screenshot,
        response.artifacts.interaction_visible_text,
        response.artifacts.interaction_accessibility,
    ):
        assert value is not None
        assert Path(value).is_file()
    _assert_diagnostic_artifacts(response)


@pytest.mark.live
async def test_live_map_view_satellite(live_session: BrowserSession) -> None:
    request = MapViewRequest(
        center="47.6062,-122.3321",
        zoom=12,
        basemap="satellite",
        layer="transit",
    )
    response = await run_map_view(request, live_session)
    assert_envelope_shape(response)
    assert response.ok is True
    assert response.extracted.resolved_url is not None
    _assert_diagnostic_artifacts(response)


@pytest.mark.live
async def test_live_place_search(live_session: BrowserSession) -> None:
    response = await run_place_search(
        PlaceSearchRequest(query="Space Needle Seattle WA"),
        live_session,
    )
    assert_envelope_shape(response)
    assert response.ok is True
    assert response.extracted.name is not None
    assert "space needle" in response.extracted.name.casefold()
    if response.extracted.rating is not None:
        assert response.extracted.rating >= 4.5
    if response.extracted.review_count is not None:
        assert response.extracted.review_count > 1_000
    _assert_diagnostic_artifacts(response)


@pytest.mark.live
async def test_live_place_details(live_session: BrowserSession) -> None:
    response = await run_place_details(
        PlaceDetailsRequest(query="Space Needle Seattle WA"),
        live_session,
    )
    assert_envelope_shape(response)
    assert response.ok is True
    assert response.extracted.name is not None
    _assert_diagnostic_artifacts(response)


@pytest.mark.live
async def test_live_distance_matrix(live_session: BrowserSession) -> None:
    response = await run_distance_matrix(
        DistanceMatrixRequest(
            origins=["Space Needle Seattle WA"],
            destinations=["Pike Place Market Seattle WA"],
            travel_mode="driving",
        ),
        live_session,
    )
    assert_envelope_shape(response)
    assert response.ok is True
    assert response.extracted.elements[0][0].status == "ok"


def _assert_diagnostic_artifacts(response: ApiEnvelope[Any]) -> None:
    artifacts = response.artifacts
    required = [
        artifacts.screenshot,
        artifacts.raw_visible_text,
        artifacts.accessibility,
        artifacts.response,
    ]
    if os.environ.get("GMAPS_TRACE") == "1":
        required.append(artifacts.trace)
    for value in required:
        assert value is not None
        assert Path(value).is_file()
