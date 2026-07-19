from __future__ import annotations

from free_gmaps_api.contracts.envelope import ApiEnvelope, ArtifactSet, Confidence
from free_gmaps_api.contracts.extracted import NotSupportedExtracted
from free_gmaps_api.contracts.requests import ElevationRequest, TimeZoneRequest


def elevation_not_supported(request: ElevationRequest) -> ApiEnvelope[NotSupportedExtracted]:
    return ApiEnvelope(
        ok=False,
        source="google_maps_web",
        request=request.model_dump(),
        maps_url=None,
        extracted=NotSupportedExtracted(
            status="not_supported",
            message=(
                "Elevation is not supported. The Google Maps web app does not expose "
                "numeric elevation data for arbitrary inputs. Use the official Elevation API "
                "for structured elevation values."
            ),
            endpoint="elevation",
        ),
        artifacts=ArtifactSet(),
        confidence=Confidence(overall="high", notes=["Intentionally not supported."]),
    )


def time_zone_not_supported(request: TimeZoneRequest) -> ApiEnvelope[NotSupportedExtracted]:
    return ApiEnvelope(
        ok=False,
        source="google_maps_web",
        request=request.model_dump(),
        maps_url=None,
        extracted=NotSupportedExtracted(
            status="not_supported",
            message=(
                "Time Zone is not supported. The Google Maps web app does not expose "
                "structured time zone data for arbitrary coordinates and timestamps. "
                "Use the official Time Zone API for timeZoneId, timeZoneName, and UTC offsets."
            ),
            endpoint="time-zone",
        ),
        artifacts=ArtifactSet(),
        confidence=Confidence(overall="high", notes=["Intentionally not supported."]),
    )
