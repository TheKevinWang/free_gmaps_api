from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from free_gmaps_api.contracts.requests import (
    DirectionsRequest,
    DistanceMatrixRequest,
    GeocodeRequest,
    MapViewRequest,
    PlaceDetailsRequest,
    PlaceSearchRequest,
    ReverseGeocodeRequest,
    StreetViewRequest,
)
from free_gmaps_api.http.backend import HttpBackend
from free_gmaps_api.settings import Settings

pytestmark = pytest.mark.live_http
_LIVE_HTTP = os.environ.get("GMAPS_LIVE_HTTP") == "1"


@pytest_asyncio.fixture(loop_scope="function")
async def live_http_backend() -> AsyncGenerator[HttpBackend]:
    if not _LIVE_HTTP:
        pytest.skip("Set GMAPS_LIVE_HTTP=1 to run live HTTP tests through GMAPS_PROXY_URL.")
    backend = HttpBackend(
        Settings(backend="http", artifact_dir=".free-gmaps-api/artifacts/live-http")
    )
    yield backend
    await backend.close()


async def test_live_http_supported_seeds(live_http_backend: HttpBackend) -> None:
    geocode = await live_http_backend.geocode(GeocodeRequest(address="Space Needle Seattle WA"))
    reverse = await live_http_backend.reverse_geocode(
        ReverseGeocodeRequest(latlng="47.6205063,-122.3492774")
    )
    place = await live_http_backend.place_search(
        PlaceSearchRequest(query="Space Needle Seattle WA")
    )
    directions = await live_http_backend.directions(
        DirectionsRequest(
            origin="Space Needle Seattle WA", destination="Pike Place Market Seattle WA"
        )
    )
    map_view = await live_http_backend.map_view(
        MapViewRequest(center="47.6062,-122.3321", zoom=12, basemap="satellite")
    )
    street_view = await live_http_backend.street_view(
        StreetViewRequest(location="39.10176,-84.5121708", size="640x360")
    )
    assert geocode.artifacts.screenshot is None
    assert reverse.artifacts.screenshot is None
    assert place.artifacts.screenshot is None
    assert directions.artifacts.screenshot is None
    assert map_view.extracted.screenshot is None
    assert street_view.extracted.screenshot is None
    assert geocode.ok is True
    assert reverse.ok is False
    assert reverse.extracted.nearest_address_or_place is None
    assert "No address-bearing place record" in reverse.confidence.notes[0]
    assert geocode.extracted.coordinates is not None
    assert abs(geocode.extracted.coordinates.lat - 47.6205063) <= 0.01
    assert abs(geocode.extracted.coordinates.lng - -122.3492774) <= 0.01
    assert place.ok is True
    assert place.extracted.name is not None
    normalized_name = place.extracted.name.casefold()
    assert "space" in normalized_name and "needle" in normalized_name
    assert place.extracted.name.strip().startswith(("[", "{")) is False
    assert len(place.extracted.name.strip()) > 1
    assert directions.ok is True
    assert directions.extracted.selected_route is not None
    assert directions.extracted.selected_route.distance_text
    assert directions.extracted.selected_route.duration_text
    matrix = await live_http_backend.distance_matrix(
        DistanceMatrixRequest(
            origins=["Space Needle Seattle WA"],
            destinations=["Pike Place Market Seattle WA"],
        )
    )
    assert matrix.ok is True
    assert len(matrix.extracted.elements) == 1
    assert len(matrix.extracted.elements[0]) == 1
    assert matrix.extracted.elements[0][0].status == "ok"
    assert map_view.extracted.requested_center == "47.6062,-122.3321"
    assert street_view.ok is True
    assert street_view.extracted.image is not None
    assert street_view.extracted.image.clean is True


async def test_live_http_place_details_requires_query_hint_and_exact_id(
    live_http_backend: HttpBackend,
) -> None:
    place_id = "ChIJ-bfVTh8VkFQRDZLQnmioK9s"

    id_only = await live_http_backend.place_details(PlaceDetailsRequest(place_id=place_id))
    combined = await live_http_backend.place_details(
        PlaceDetailsRequest(query="Space Needle Seattle WA", place_id=place_id)
    )

    assert id_only.ok is False
    assert "human query hint" in id_only.confidence.notes[0]
    assert combined.ok is True
    assert combined.extracted.official_place_id == place_id
    assert combined.extracted.name is not None
    assert {"space", "needle"} <= set(combined.extracted.name.casefold().split())


async def test_live_http_address_street_view_uses_maps_place_preview(
    live_http_backend: HttpBackend,
) -> None:
    response = await live_http_backend.street_view(
        StreetViewRequest(
            location="520 Vine St, Cincinnati, OH 45202",
            heading=45.0,
            pitch=0.0,
            fov=80.0,
            size="640x360",
        )
    )

    assert response.ok is True
    assert response.extracted.image_key == "GIU5brlvluQSo91oArkvHg"
    assert response.extracted.capture_date == "2025-05"
    assert response.extracted.resolved_coordinates is not None
    assert response.extracted.resolved_coordinates.lat == pytest.approx(39.10174390985246)
    assert response.extracted.resolved_coordinates.lng == pytest.approx(-84.51309369275354)
    assert response.extracted.location_resolution is not None
    assert response.extracted.location_resolution.source == "maps_place_photo"
    assert response.extracted.image is not None
    assert response.extracted.image.clean is True
    assert (response.extracted.image.width, response.extracted.image.height) == (640, 360)
