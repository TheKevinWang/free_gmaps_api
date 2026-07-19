from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from free_gmaps_api.app import create_app
from free_gmaps_api.contracts.requests import (
    DirectionsRequest,
    DistanceMatrixRequest,
    GeocodeRequest,
    MapViewRequest,
    PlaceDetailsRequest,
    StreetViewRequest,
)
from free_gmaps_api.http.backend import HttpBackend
from free_gmaps_api.http.client import MapsHttpClient
from free_gmaps_api.settings import Settings


def _html() -> str:
    state = [
        "Space Needle",
        "Observation deck",
        "4.7 (20,000)",
        "400 Broad St, Seattle, WA",
        "47.6205063, -122.3492774",
        "12 min",
        "1.0 mile",
        "via 2nd Ave",
        "Fastest route now",
    ]
    import json

    return f"<script>window.APP_INITIALIZATION_STATE={json.dumps(state)};</script>"


def _jpeg(width: int, height: int) -> bytes:
    return (
        b"\xff\xd8\xff\xc0\x00\x08\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x00\xff\xd9"
    )


def _place_photo_batch() -> bytes:
    pano_id = "GIU5brlvluQSo91oArkvHg"
    renderer = (
        "https://streetviewpixels-pa.googleapis.com/v1/thumbnail"
        f"?panoid={pano_id}&cb_client=maps_sv.tactile.gps"
        "&w=203&h=100&yaw=77.547066&pitch=0&thumbfov=100"
    )
    record = [
        pano_id,
        0,
        1,
        None,
        None,
        None,
        [renderer, "", None, [203, 100]],
        None,
        [[3, -84.51309369275354, 39.10174390985246], [77.547066, 90]],
        None,
        [[2025, 5, 25, 16]],
    ]
    nested = json.dumps([[[record]]], separators=(",", ":"))
    chunk = json.dumps(
        [["wrb.fr", "/MapsPhotoService.ListEntityPhotos", nested, None, None, None]],
        separators=(",", ":"),
    ).encode()
    return b")]}'\n\n" + str(len(chunk)).encode() + b"\n" + chunk


@pytest.fixture
def http_backend(tmp_path: object) -> HttpBackend:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.google.com"
        if request.url.path == "/search":
            assert request.url.params["tbm"] == "map"
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[
                    ["unrelated", [51.7546255, 35.502669]],
                    [
                        "Space Needle",
                        "400 Broad St, Seattle, WA 98109",
                        [47.6205063, -122.3492774],
                        "ChIJ-bfVTh8VkFQRDZLQnmioK9s",
                    ],
                ],
                request=request,
            )
        if request.url.path == "/maps/preview/directions":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[
                    [
                        "Space Needle, Seattle, WA",
                        "Pike Place Market, Seattle, WA",
                        ["12 min", "1.0 mile", "via 2nd Ave", "Fastest route now"],
                    ],
                ],
                request=request,
            )
        return httpx.Response(
            200, headers={"content-type": "text/html"}, text=_html(), request=request
        )

    settings = Settings(artifact_dir=str(tmp_path), proxy_url="socks5://localhost:9050")
    client = MapsHttpClient(settings, transport=httpx.MockTransport(handler))
    return HttpBackend(settings, client=client)


async def test_http_backend_serves_mocked_geocode_without_browser(
    http_backend: HttpBackend,
) -> None:
    response = await http_backend.geocode(GeocodeRequest(address="Space Needle Seattle WA"))
    assert response.ok is True
    assert response.extracted.coordinates is not None
    assert response.extracted.coordinates.lat == pytest.approx(47.6205063)
    assert response.artifacts.screenshot is None
    assert response.artifacts.response is not None
    await http_backend.close()


async def test_http_backend_defensively_rejects_bypassed_empty_matrix(
    http_backend: HttpBackend,
) -> None:
    invalid = DistanceMatrixRequest.model_construct(origins=[], destinations=["B"])

    response = await http_backend.distance_matrix(invalid)

    assert response.ok is False
    assert response.extracted.elements == []
    assert response.confidence.notes == ["All matrix element lookups failed."]
    await http_backend.close()


async def test_http_backend_rejects_unanchored_place_false_success(tmp_path: object) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[["m", [51.7546255, 35.502669]]],
                request=request,
            )
        return httpx.Response(
            200, headers={"content-type": "text/html"}, text=_html(), request=request
        )

    settings = Settings(artifact_dir=str(tmp_path), proxy_url="socks5://localhost:9050")
    backend = HttpBackend(
        settings, client=MapsHttpClient(settings, transport=httpx.MockTransport(handler))
    )
    try:
        response = await backend.geocode(GeocodeRequest(address="Space Needle Seattle WA"))
    finally:
        await backend.close()

    assert response.ok is False
    assert response.extracted.coordinates is None
    assert response.extracted.display_name is None


async def test_http_place_details_requires_query_hint_for_official_id(
    http_backend: HttpBackend,
) -> None:
    response = await http_backend.place_details(
        PlaceDetailsRequest(place_id="ChIJ-bfVTh8VkFQRDZLQnmioK9s")
    )

    assert response.ok is False
    assert response.extracted.official_place_id is None
    assert "human query hint" in response.confidence.notes[0]
    await http_backend.close()


async def test_http_place_details_accepts_query_only_with_exact_official_id(
    http_backend: HttpBackend,
) -> None:
    response = await http_backend.place_details(
        PlaceDetailsRequest(
            query="Space Needle Seattle WA",
            place_id="ChIJ-bfVTh8VkFQRDZLQnmioK9s",
        )
    )

    assert response.ok is True
    assert response.extracted.official_place_id == "ChIJ-bfVTh8VkFQRDZLQnmioK9s"
    assert response.extracted.coordinates is not None
    await http_backend.close()


@pytest.mark.parametrize(
    "maps_url",
    [
        "https://example.com/maps/place/Space+Needle",
        "http://127.0.0.1/maps/place/Space+Needle",
        "file:///etc/passwd",
    ],
)
async def test_http_place_details_rejects_noncanonical_maps_url(
    http_backend: HttpBackend, maps_url: str
) -> None:
    response = await http_backend.place_details(PlaceDetailsRequest(maps_url=maps_url))

    assert response.ok is False
    assert response.artifacts.response is None
    await http_backend.close()


async def test_http_backend_returns_error_for_malformed_street_view_image(
    tmp_path: object,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/maps/photometa/si/v1":
            metadata = (
                '["https://lh3.googleusercontent.com/example=w0-h0-k-no",'
                "[[null,null,39.10176,-84.5121708],null,[90,0,0]]]"
            )
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                text=metadata,
                request=request,
            )
        if request.url.host == "lh3.googleusercontent.com":
            return httpx.Response(
                200,
                headers={"content-type": "image/jpeg"},
                content=b"not-an-image",
                request=request,
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=_html(),
            request=request,
        )

    settings = Settings(artifact_dir=str(tmp_path), proxy_url="socks5://localhost:9050")
    backend = HttpBackend(
        settings, client=MapsHttpClient(settings, transport=httpx.MockTransport(handler))
    )
    try:
        response = await backend.street_view(
            StreetViewRequest(location="39.10176,-84.5121708", size="640x360")
        )
    finally:
        await backend.close()

    assert response.ok is False
    assert response.confidence.overall == "low"
    assert "invalid image bytes" in response.confidence.notes[0]
    assert response.extracted.image is None


async def test_http_address_street_view_uses_place_linked_exact_panorama(tmp_path: object) -> None:
    place_url = (
        "https://www.google.com/maps/preview/place/520+Vine+St,+Cincinnati,+OH+45202,+USA/"
        "@39.1017693,-84.5127768,3096a,13.1y/"
        "data=!4m2!3m1!1s0x8841b15093c01a61:0xcc7b27017af0ac27"
    )
    metadata_requested = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal metadata_requested
        if request.url.path == "/search":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[
                    [
                        "520 Vine Building",
                        "520 Vine St, Cincinnati, OH 45202",
                        [39.1017693, -84.5127768],
                        place_url,
                    ]
                ],
                request=request,
            )
        if request.url.path == "/maps/_/MapsWizUi/data/batchexecute":
            assert request.method == "POST"
            assert request.url.params["rpcids"] == "hspqX"
            assert b"0x8841b15093c01a61%3A0xcc7b27017af0ac27" in request.content
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=_place_photo_batch(),
                request=request,
            )
        if request.url.path == "/maps/photometa/si/v1":
            metadata_requested = True
            raise AssertionError("Address selection must not fall back to coordinate metadata.")
        if request.url.host == "streetviewpixels-pa.googleapis.com":
            assert request.url.params["panoid"] == "GIU5brlvluQSo91oArkvHg"
            assert request.url.params["yaw"] == "45"
            assert request.url.params["pitch"] == "0"
            assert request.url.params["thumbfov"] == "80"
            assert "Chrome/" in request.headers["user-agent"]
            return httpx.Response(
                200,
                headers={"content-type": "image/jpeg"},
                content=_jpeg(640, 360),
                request=request,
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=_html(),
            request=request,
        )

    settings = Settings(artifact_dir=str(tmp_path), proxy_url="socks5://localhost:9050")
    backend = HttpBackend(
        settings, client=MapsHttpClient(settings, transport=httpx.MockTransport(handler))
    )
    try:
        response = await backend.street_view(
            StreetViewRequest(
                location="520 Vine St, Cincinnati, OH 45202",
                heading=45.0,
                pitch=0.0,
                fov=80.0,
                size="640x360",
            )
        )
    finally:
        await backend.close()

    assert response.ok is True
    assert metadata_requested is False
    assert response.extracted.image_key == "GIU5brlvluQSo91oArkvHg"
    assert response.extracted.capture_date == "2025-05"
    assert response.extracted.requested_viewpoint is not None
    assert response.extracted.requested_viewpoint.lng == pytest.approx(-84.5127768)
    assert response.extracted.resolved_coordinates is not None
    assert response.extracted.resolved_coordinates.lng == pytest.approx(-84.51309369275354)
    assert response.extracted.location_resolution is not None
    assert response.extracted.location_resolution.source == "maps_place_photo"
    assert response.extracted.image is not None
    assert response.extracted.image.width == 640
    assert response.extracted.image.height == 360


async def test_http_exact_pano_does_not_require_location(tmp_path: object) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "streetviewpixels-pa.googleapis.com":
            assert request.url.params["panoid"] == "GIU5brlvluQSo91oArkvHg"
            return httpx.Response(
                200,
                headers={"content-type": "image/jpeg"},
                content=_jpeg(640, 360),
                request=request,
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=_html(),
            request=request,
        )

    settings = Settings(artifact_dir=str(tmp_path), proxy_url="socks5://localhost:9050")
    backend = HttpBackend(
        settings, client=MapsHttpClient(settings, transport=httpx.MockTransport(handler))
    )
    try:
        response = await backend.street_view(
            StreetViewRequest(pano="GIU5brlvluQSo91oArkvHg", size="640x360")
        )
    finally:
        await backend.close()

    assert response.ok is True
    assert response.extracted.image_key == "GIU5brlvluQSo91oArkvHg"
    assert response.extracted.requested_viewpoint is None


async def test_http_invalid_exact_pano_returns_error_without_network(tmp_path: object) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Invalid panorama ID made a network request: {request.url}")

    settings = Settings(artifact_dir=str(tmp_path), proxy_url="socks5://localhost:9050")
    backend = HttpBackend(
        settings, client=MapsHttpClient(settings, transport=httpx.MockTransport(handler))
    )
    try:
        response = await backend.street_view(StreetViewRequest(pano=" "))
    finally:
        await backend.close()

    assert response.ok is False
    assert response.extracted.requested_pano == " "
    assert "empty or invalid" in response.confidence.notes[0]


async def test_http_backend_parses_mocked_directions_and_truthful_map_artifacts(
    http_backend: HttpBackend,
) -> None:
    directions = await http_backend.directions(
        DirectionsRequest(origin="Space Needle", destination="Pike Place Market")
    )
    map_view = await http_backend.map_view(MapViewRequest(center="47.6062,-122.3321", zoom=12))
    assert directions.ok is True
    assert directions.extracted.selected_route is not None
    assert directions.extracted.selected_route.duration_text == "12 min"
    assert map_view.ok is True
    assert map_view.extracted.screenshot is None
    assert "does not render" in map_view.confidence.notes[0]
    await http_backend.close()


def test_settings_default_to_http_after_live_gate_passes() -> None:
    assert Settings().backend == "http"
    with pytest.raises(ValueError, match="host and port"):
        Settings(proxy_url="socks5://localhost")


def test_default_application_health_uses_http_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GMAPS_BACKEND", raising=False)
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["backend"] == "http"


def test_application_rejects_oversized_geocode_as_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GMAPS_BACKEND", raising=False)
    with TestClient(create_app()) as client:
        response = client.post("/v1/geocode", json={"address": "x" * 3000})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
