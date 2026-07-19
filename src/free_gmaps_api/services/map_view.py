from __future__ import annotations

import uuid

from free_gmaps_api.browser.artifacts import artifact_set_from_navigation
from free_gmaps_api.browser.extract import extract_coordinates_from_url, extract_zoom_from_url
from free_gmaps_api.browser.session import BrowserSession
from free_gmaps_api.contracts.envelope import ApiEnvelope, ArtifactSet, Confidence, UnsupportedField
from free_gmaps_api.contracts.extracted import (
    CoordinatePair,
    MapViewExtracted,
    StreetViewScreenshot,
)
from free_gmaps_api.contracts.requests import MapViewRequest
from free_gmaps_api.maps_urls.map_view import build_map_view_url
from free_gmaps_api.support.matrix import get_unsupported_fields


async def run_map_view(
    request: MapViewRequest,
    session: BrowserSession,
) -> ApiEnvelope[MapViewExtracted]:
    request_id = uuid.uuid4().hex
    unsupported = get_unsupported_fields("map-view", request)

    maps_url = build_map_view_url(
        center=request.center,
        zoom=request.zoom,
        basemap=request.basemap,
        layer=request.layer,
    )

    try:
        viewport = request.viewport
        nav_result = await session.navigate(
            maps_url,
            request_id=request_id,
            viewport=(viewport.width, viewport.height) if viewport is not None else None,
        )
    except Exception as exc:
        return _map_view_error(request, str(exc), unsupported)

    current_url = str(nav_result["current_url"])
    screenshot_path = str(nav_result.get("screenshot", ""))

    coords_tuple = extract_coordinates_from_url(current_url)
    resolved_center: CoordinatePair | None = None
    if coords_tuple:
        resolved_center = CoordinatePair(lat=coords_tuple[0], lng=coords_tuple[1])

    zoom = extract_zoom_from_url(current_url)

    screenshot = StreetViewScreenshot(
        path=screenshot_path,
        width=viewport.width if viewport else None,
        height=viewport.height if viewport else None,
    )

    extracted = MapViewExtracted(
        requested_center=request.center,
        requested_zoom=request.zoom,
        requested_basemap=request.basemap,
        requested_layer=request.layer,
        resolved_url=current_url,
        resolved_center=resolved_center,
        resolved_zoom=zoom,
        screenshot=screenshot,
        unsupported_api_fields=unsupported,
    )

    return ApiEnvelope(
        ok=True,
        source="google_maps_web",
        request=request.model_dump(),
        maps_url=maps_url,
        extracted=extracted,
        artifacts=artifact_set_from_navigation(nav_result),
        confidence=Confidence(overall="high", notes=[]),
    )


def _map_view_error(
    request: MapViewRequest,
    message: str,
    unsupported: list[UnsupportedField],
) -> ApiEnvelope[MapViewExtracted]:
    return ApiEnvelope(
        ok=False,
        source="google_maps_web",
        request=request.model_dump(),
        maps_url=None,
        extracted=MapViewExtracted(
            requested_center=request.center,
            requested_zoom=request.zoom,
            requested_basemap=request.basemap,
            requested_layer=request.layer,
            unsupported_api_fields=unsupported,
        ),
        artifacts=ArtifactSet(),
        confidence=Confidence(overall="low", notes=[message]),
    )
