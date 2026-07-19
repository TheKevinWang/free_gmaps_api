from __future__ import annotations

from free_gmaps_api.contracts.requests import ElevationRequest, TimeZoneRequest
from free_gmaps_api.services.unsupported import elevation_not_supported, time_zone_not_supported
from tests.helpers.assert_envelope import assert_envelope_shape


def test_elevation_not_supported() -> None:
    request = ElevationRequest(locations=["Denver,CO"])
    response = elevation_not_supported(request)
    assert_envelope_shape(response)
    assert response.ok is False
    assert response.extracted.status == "not_supported"
    assert response.extracted.endpoint == "elevation"


def test_time_zone_not_supported() -> None:
    request = TimeZoneRequest(location="47.6062,-122.3321", timestamp=1609459200)
    response = time_zone_not_supported(request)
    assert_envelope_shape(response)
    assert response.ok is False
    assert response.extracted.status == "not_supported"
    assert response.extracted.endpoint == "time-zone"


def test_elevation_envelope_shape() -> None:
    request = ElevationRequest(locations=["Mount Rainier WA"])
    response = elevation_not_supported(request)
    assert response.source == "google_maps_web"
    assert response.maps_url is None
    assert "not supported" in response.extracted.message.lower()


def test_time_zone_message_content() -> None:
    request = TimeZoneRequest(location="51.5074,-0.1278")
    response = time_zone_not_supported(request)
    assert (
        "timeZoneId" in response.extracted.message
        or "time zone" in response.extracted.message.lower()
    )
