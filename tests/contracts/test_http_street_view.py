from __future__ import annotations

import json

import pytest

from free_gmaps_api.http.street_view import (
    PlaceStreetViewParseError,
    exact_panorama_renderer_url,
    parse_place_street_view_response,
    place_identity_from_url,
)

_PANO = "GIU5brlvluQSo91oArkvHg"
_CAMERA_LAT = 39.10174390985246
_CAMERA_LNG = -84.51309369275354


def _batch_response(
    *,
    pano_id: str = _PANO,
    renderer_pano_id: str = _PANO,
    coordinates: list[object] | None = None,
    service: str = "/MapsPhotoService.ListEntityPhotos",
) -> bytes:
    renderer = (
        "https://streetviewpixels-pa.googleapis.com/v1/thumbnail"
        f"?panoid={renderer_pano_id}&cb_client=maps_sv.tactile.gps"
        "&w=203&h=100&yaw=77.547066&pitch=0&thumbfov=100"
    )
    record: list[object] = [
        pano_id,
        0,
        1,
        None,
        None,
        None,
        [renderer, "", None, [203, 100]],
        None,
        [coordinates or [3, _CAMERA_LNG, _CAMERA_LAT], [77.547066, 90]],
        None,
        [[2025, 5, 25, 16]],
    ]
    nested = json.dumps([[[record]]], separators=(",", ":"))
    chunk = json.dumps(
        [["wrb.fr", service, nested, None, None, None, "generic"]],
        separators=(",", ":"),
    ).encode()
    return b")]}'\n\n" + str(len(chunk)).encode() + b"\n" + chunk


def test_place_identity_uses_internal_feature_id_and_canonical_path() -> None:
    url = (
        "https://www.google.com/maps/place/520+Vine+St/@39.1017693,-84.5127768,17z/"
        "data=!3m1!4b1!4m6!3m5!1s0x8841b15093c01a61:0xcc7b27017af0ac27"
        "!8m2!3d39.1017693!4d-84.5127768!16s%2Fg%2F11bw42nv2k?entry=ttu"
    )

    identity = place_identity_from_url(url)

    assert identity is not None
    assert identity.feature_id == "0x8841b15093c01a61:0xcc7b27017af0ac27"
    assert identity.source_path.startswith("/maps/place/520+Vine+St/")
    assert "entry=ttu" not in identity.canonical_url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/maps/place/520+Vine+St/0x1:0x2",
        "http://www.google.com/maps/place/520+Vine+St/0x1:0x2",
        "https://www.google.com/search?q=520+Vine+St",
        "https://www.google.com/maps/place/520+Vine+St",
    ],
)
def test_place_identity_rejects_unsafe_or_incomplete_urls(url: str) -> None:
    assert place_identity_from_url(url) is None


def test_place_photo_parser_returns_co_located_panorama_evidence() -> None:
    panorama = parse_place_street_view_response(_batch_response())

    assert panorama.pano_id == _PANO
    assert panorama.coordinates.lat == pytest.approx(_CAMERA_LAT)
    assert panorama.coordinates.lng == pytest.approx(_CAMERA_LNG)
    assert panorama.heading == pytest.approx(77.547066)
    assert panorama.capture_date == "2025-05"
    assert f"panoid={_PANO}" in panorama.renderer_url


@pytest.mark.parametrize(
    "body,error",
    [
        (b"[]", "anti-XSSI"),
        (_batch_response(service="/WrongService"), "expected service"),
        (_batch_response(renderer_pano_id="different"), "valid Street View"),
        (
            _batch_response(coordinates=[3, 500.0, 200.0]),
            "valid Street View",
        ),
    ],
)
def test_place_photo_parser_fails_closed_on_untrusted_shapes(body: bytes, error: str) -> None:
    with pytest.raises(PlaceStreetViewParseError, match=error):
        parse_place_street_view_response(body)


def test_exact_panorama_renderer_url_validates_id() -> None:
    renderer = exact_panorama_renderer_url(_PANO)
    assert renderer.startswith("https://streetviewpixels-pa.googleapis.com/v1/thumbnail?")
    assert f"panoid={_PANO}" in renderer
    with pytest.raises(ValueError, match="empty or invalid"):
        exact_panorama_renderer_url("\n")
