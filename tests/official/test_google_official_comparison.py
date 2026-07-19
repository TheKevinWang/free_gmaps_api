from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from free_gmaps_api.backends.base import MapsBackend
from free_gmaps_api.contracts.extracted import CoordinatePair
from free_gmaps_api.contracts.requests import (
    DirectionsRequest,
    DistanceMatrixRequest,
    GeocodeRequest,
    PlaceSearchRequest,
    StreetViewRequest,
)
from free_gmaps_api.settings import Settings
from tests.helpers.assert_envelope import (
    assert_envelope_shape,
    assert_no_unexpected_official_fields,
)
from tests.helpers.backends import build_test_backend
from tests.official.google_maps_client import (
    OfficialCoordinate,
    OfficialPlaceResult,
    official_client,
)

pytestmark = pytest.mark.official

_OFFICIAL_COMPARE = os.environ.get("GOOGLE_OFFICIAL_COMPARE") == "1"


@pytest.fixture
async def selected_backend() -> AsyncIterator[MapsBackend]:
    _require_api_key()
    backend_name = os.environ.get("GOOGLE_OFFICIAL_BACKEND", "zendriver")
    if backend_name not in {"http", "zendriver"}:
        pytest.fail("GOOGLE_OFFICIAL_BACKEND must be 'http' or 'zendriver'.")
    backend = build_test_backend(
        Settings(
            backend=backend_name,  # type: ignore[arg-type]
            artifact_dir=".free-gmaps-api/artifacts/official",
        )
    )
    try:
        yield backend
    finally:
        await backend.close()


@pytest.mark.official
async def test_geocode_contract_matches_official_coordinates(
    selected_backend: MapsBackend,
) -> None:
    request = GeocodeRequest(address="Space Needle Seattle WA")

    with official_client(_require_api_key()) as client:
        official = client.geocode(request.address or "")

    response = await selected_backend.geocode(request)

    assert_envelope_shape(response)
    assert_no_unexpected_official_fields("geocode", request, response)
    assert response.ok is True
    assert response.extracted.coordinates is not None
    _assert_coordinates_close(
        response.extracted.coordinates,
        official.location,
        tolerance_degrees=0.01,
    )


@pytest.mark.official
async def test_place_search_contract_matches_official_claimed_fields(
    selected_backend: MapsBackend,
) -> None:
    request = PlaceSearchRequest(
        query="Space Needle Seattle WA",
        fields=["displayName", "formattedAddress", "location", "rating", "userRatingCount"],
    )

    with official_client(_require_api_key()) as client:
        official = client.text_search(request.query)

    response = await selected_backend.place_search(request)

    assert_envelope_shape(response)
    assert_no_unexpected_official_fields("place-search", request, response)
    assert response.ok is True
    if response.extracted.name is not None:
        _assert_name_overlaps(response.extracted.name, official)
    if response.extracted.coordinates is not None and official.location is not None:
        _assert_coordinates_close(
            response.extracted.coordinates,
            official.location,
            tolerance_degrees=0.01,
        )
    if response.extracted.rating is not None:
        assert official.rating is not None
        assert abs(response.extracted.rating - official.rating) <= 0.5
    if response.extracted.review_count is not None:
        assert official.user_rating_count is not None
        smaller = min(response.extracted.review_count, official.user_rating_count)
        larger = max(response.extracted.review_count, official.user_rating_count)
        assert smaller > 0 and larger / smaller <= 2.0


@pytest.mark.official
async def test_distance_matrix_contract_matches_official_matrix_shape(
    selected_backend: MapsBackend,
) -> None:
    request = DistanceMatrixRequest(
        origins=["Space Needle Seattle WA"],
        destinations=["Pike Place Market Seattle WA"],
        travel_mode="driving",
    )

    with official_client(_require_api_key()) as client:
        official = client.distance_matrix(
            origins=request.origins,
            destinations=request.destinations,
            travel_mode=request.travel_mode,
        )

    response = await selected_backend.distance_matrix(request)

    assert_envelope_shape(response)
    assert_no_unexpected_official_fields("distance-matrix", request, response)
    assert len(response.extracted.elements) == len(official.rows)
    assert len(response.extracted.elements[0]) == len(official.rows[0])

    browser_element = response.extracted.elements[0][0]
    official_element = official.rows[0][0]
    if browser_element.status == "ok":
        assert official_element.status == "OK"
        if browser_element.distance_text is not None:
            assert official_element.distance_text is not None
        if browser_element.duration_text is not None:
            assert official_element.duration_text is not None


@pytest.mark.official
async def test_directions_contract_matches_official_selected_route(
    selected_backend: MapsBackend,
) -> None:
    request = DirectionsRequest(
        origin="Space Needle Seattle WA",
        destination="Pike Place Market Seattle WA",
        travel_mode="driving",
        alternatives=True,
    )

    with official_client(_require_api_key()) as client:
        official = client.compute_routes(
            origin=request.origin,
            destination=request.destination,
            alternatives=request.alternatives,
        )

    response = await selected_backend.directions(request)

    assert_envelope_shape(response)
    assert_no_unexpected_official_fields("directions", request, response)
    assert response.ok is True
    assert response.extracted.selected_route is not None
    browser_route = response.extracted.selected_route
    official_route = official.routes[0]
    assert browser_route.duration_seconds_approximate is not None
    assert browser_route.distance_meters_approximate is not None
    assert abs(browser_route.duration_seconds_approximate - official_route.duration_seconds) <= 300
    assert abs(browser_route.distance_meters_approximate - official_route.distance_meters) <= 500
    if len(official.routes) > 1:
        assert len(response.extracted.routes) >= 2


@pytest.mark.official
async def test_street_view_contract_matches_official_metadata(
    selected_backend: MapsBackend,
) -> None:
    """Compare a clean web renderer image with one billed Static API image request."""
    location = "520 Vine St, Cincinnati, OH 45202"
    heading = 45.0
    pitch = 0.0
    fov = 80.0
    size = "640x360"

    with official_client(_require_api_key()) as client:
        metadata = client.street_view_metadata(location=location)

    request = StreetViewRequest(
        location=location,
        heading=heading,
        pitch=pitch,
        fov=fov,
        size=size,
    )
    response = await selected_backend.street_view(request)

    assert_envelope_shape(response)
    assert_no_unexpected_official_fields("street-view", request, response)

    # ok must match whether the official metadata reports imagery at this location
    if metadata.status == "OK":
        assert response.ok is True, (
            f"Official metadata reports imagery exists but browser ok=False. "
            f"Confidence notes: {response.confidence.notes}"
        )

    # Coordinates must be within tolerance of the authoritative panorama location
    if (
        response.ok
        and metadata.location is not None
        and response.extracted.resolved_coordinates is not None
    ):
        _assert_coordinates_close(
            response.extracted.resolved_coordinates,
            metadata.location,
            tolerance_degrees=0.01,
        )

    # The primary image comes from the Maps web renderer. Only the explicit
    # browser backend also returns a full-page diagnostic screenshot.
    assert response.source == "google_maps_web"
    if response.ok:
        assert response.extracted.image is not None, "ok=True but no primary image returned"
        assert response.extracted.image.clean is True
        assert response.extracted.image.source == "web_renderer"
        assert response.extracted.image.width == 640
        assert response.extracted.image.height == 360
        if os.environ.get("GOOGLE_OFFICIAL_BACKEND", "zendriver") == "http":
            assert response.extracted.screenshot is None
            assert response.extracted.image_key == metadata.pano_id
        else:
            assert response.extracted.screenshot is not None, "ok=True but no screenshot captured"
            assert response.extracted.screenshot.path != "", "Screenshot path must be non-empty"
        assert response.artifacts.street_view_image == response.extracted.image.path

    assert metadata.pano_id is not None, "Official metadata returned no panorama ID."
    with official_client(_require_api_key()) as client:
        official_image = client.street_view_image(
            pano=metadata.pano_id,
            size=size,
            heading=heading,
            pitch=pitch,
            fov=fov,
        )

    assert response.extracted.image is not None
    _assert_images_similar(
        Path(response.extracted.image.path),
        official_image.content,
        max_normalized_mean_error=(
            0.05 if os.environ.get("GOOGLE_OFFICIAL_BACKEND", "zendriver") == "http" else 0.16
        ),
    )

    # Request parameters must be echoed back in extracted
    assert response.extracted.requested_location == location
    assert response.extracted.requested_heading == heading
    assert response.extracted.requested_pitch == pitch
    assert response.extracted.requested_fov == fov


def _assert_images_similar(
    browser_path: Path,
    official_content: bytes,
    *,
    max_normalized_mean_error: float,
) -> None:
    with Image.open(browser_path) as browser_source:
        browser = browser_source.convert("RGB")
    with Image.open(BytesIO(official_content)) as official_source:
        official = official_source.convert("RGB")

    assert browser.size == official.size
    comparison_height = max(1, official.height - 24)
    box = (0, 0, official.width, comparison_height)
    difference = ImageChops.difference(browser.crop(box), official.crop(box))
    channel_means = ImageStat.Stat(difference).mean
    normalized_mean_error = sum(channel_means) / (len(channel_means) * 255.0)
    assert normalized_mean_error <= max_normalized_mean_error, (
        "Clean Maps web image differs from the official Street View Static API image: "
        f"normalized_mean_error={normalized_mean_error:.4f}, "
        f"threshold={max_normalized_mean_error:.4f}"
    )


def _require_api_key() -> str:
    if not _OFFICIAL_COMPARE:
        pytest.skip("Set GOOGLE_OFFICIAL_COMPARE=1 to run official API comparison tests.")
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        pytest.skip("Set GOOGLE_MAPS_API_KEY to run official API comparison tests.")
    return api_key


def _assert_coordinates_close(
    browser_coordinates: CoordinatePair,
    official_coordinates: OfficialCoordinate,
    tolerance_degrees: float,
) -> None:
    lat_delta = abs(browser_coordinates.lat - official_coordinates.lat)
    lng_delta = abs(browser_coordinates.lng - official_coordinates.lng)
    assert lat_delta <= tolerance_degrees and lng_delta <= tolerance_degrees, (
        "Browser-backed coordinates differ from official coordinates beyond tolerance: "
        f"browser=({browser_coordinates.lat}, {browser_coordinates.lng}), "
        f"official=({official_coordinates.lat}, {official_coordinates.lng}), "
        f"tolerance={tolerance_degrees}"
    )


def _assert_name_overlaps(browser_name: str, official: OfficialPlaceResult) -> None:
    if official.display_name is None:
        return
    official_tokens = _tokens(official.display_name)
    browser_tokens = _tokens(browser_name)
    missing = official_tokens - browser_tokens
    assert not missing, (
        "Browser-backed place name did not include official display-name tokens: "
        f"browser={browser_name!r}, official={official.display_name!r}, missing={missing}"
    )


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 1}
