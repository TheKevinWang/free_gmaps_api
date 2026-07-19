from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx

from free_gmaps_api.browser.artifacts import artifact_set_from_navigation
from free_gmaps_api.browser.extract import (
    extract_coordinates_from_url,
    extract_orientation_from_url,
)
from free_gmaps_api.browser.session import BrowserSession
from free_gmaps_api.browser.street_view_image import (
    download_clean_street_view_image,
    image_dimensions_from_file,
    parse_size,
    renderer_url_from_metadata,
)
from free_gmaps_api.contracts.envelope import ApiEnvelope, ArtifactSet, Confidence, UnsupportedField
from free_gmaps_api.contracts.extracted import (
    CoordinatePair,
    LocationResolution,
    StreetViewExtracted,
    StreetViewImage,
    StreetViewOrientation,
    StreetViewScreenshot,
)
from free_gmaps_api.contracts.requests import StreetViewRequest
from free_gmaps_api.maps_urls.search import build_search_url
from free_gmaps_api.maps_urls.street_view import build_street_view_url
from free_gmaps_api.support.matrix import get_unsupported_fields


async def run_street_view(
    request: StreetViewRequest,
    session: BrowserSession,
    *,
    image_client: httpx.AsyncClient | None = None,
) -> ApiEnvelope[StreetViewExtracted]:
    request_id = uuid.uuid4().hex
    unsupported = get_unsupported_fields("street-view", request)

    location_resolution: LocationResolution | None = None
    viewpoint: CoordinatePair | None = None
    resolved_coords: CoordinatePair | None = None

    if request.location:
        loc = request.location.strip()
        coords = _try_parse_latlng(loc)
        if coords:
            viewpoint = CoordinatePair(lat=coords[0], lng=coords[1])
            location_resolution = LocationResolution(
                display_text=loc,
                coordinates=viewpoint,
                source="caller_input",
            )
        else:
            search_url = build_search_url(loc)
            try:
                nav_result = await session.navigate(search_url, request_id=f"{request_id}_search")
                resolved_url: str = str(nav_result["current_url"])
                candidate_urls = [resolved_url]
                raw_candidates = nav_result.get("candidate_maps_urls", [])
                if isinstance(raw_candidates, list):
                    candidate_urls.extend(str(url) for url in raw_candidates)
                coords_from_url = next(
                    (
                        coords
                        for candidate in candidate_urls
                        if (coords := extract_coordinates_from_url(candidate)) is not None
                    ),
                    None,
                )
                if coords_from_url:
                    resolved_coords = CoordinatePair(lat=coords_from_url[0], lng=coords_from_url[1])
                    viewpoint = resolved_coords
                location_resolution = LocationResolution(
                    display_text=loc,
                    place_url=resolved_url,
                    coordinates=resolved_coords,
                    source="url",
                )
            except Exception as exc:
                return _error_envelope(request, str(exc), unsupported)

    if viewpoint is None:
        return _error_envelope(
            request,
            "No resolvable location or viewpoint. "
            "Provide 'location' as address text or lat,lng coordinates.",
            unsupported,
        )

    sv_url = build_street_view_url(
        viewpoint=f"{viewpoint.lat},{viewpoint.lng}",
        heading=request.heading,
        pitch=request.pitch,
        fov=request.fov,
        pano=request.pano,
    )

    try:
        viewport = request.viewport
        nav_result = await session.navigate(
            sv_url,
            request_id=request_id,
            viewport=(viewport.width, viewport.height) if viewport is not None else None,
        )
    except Exception as exc:
        return _error_envelope(request, str(exc), unsupported)

    current_url = str(nav_result["current_url"])
    screenshot_value = nav_result.get("screenshot")
    screenshot_path = str(screenshot_value) if screenshot_value else None

    renderer_urls = [current_url]
    raw_candidates = nav_result.get("candidate_maps_urls", [])
    if isinstance(raw_candidates, list):
        renderer_urls.extend(str(url) for url in raw_candidates)
    metadata_body = nav_result.get("street_view_metadata_body")
    if isinstance(metadata_body, str):
        metadata_renderer = renderer_url_from_metadata(
            metadata_body,
            heading=request.heading,
            pitch=request.pitch,
            fov=request.fov,
        )
        if metadata_renderer is not None:
            renderer_urls.insert(0, metadata_renderer)
    requested_width: int | None = None
    requested_height: int | None = None
    if request.size is not None:
        requested_width, requested_height = parse_size(request.size)
    elif viewport is not None:
        requested_width, requested_height = viewport.width, viewport.height

    clean_image = None
    clean_image_error: str | None = None
    artifact_dir_value = nav_result.get("artifact_dir")
    if artifact_dir_value is not None:
        try:
            clean_image = await download_clean_street_view_image(
                renderer_urls,
                Path(str(artifact_dir_value)),
                requested_width,
                requested_height,
                request.fov,
                timeout_seconds=float(getattr(session, "timeout_seconds", 30.0)),
                client=image_client,
            )
        except Exception as exc:
            clean_image_error = f"{type(exc).__name__}: {exc}"

    if clean_image is not None:
        nav_result["street_view_image"] = clean_image.path
        primary_image = StreetViewImage(
            path=clean_image.path,
            width=clean_image.width,
            height=clean_image.height,
            content_type=clean_image.content_type,
            source="web_renderer",
            clean=True,
        )
    elif screenshot_path is not None:
        screenshot_dimensions = image_dimensions_from_file(screenshot_path)
        primary_image = StreetViewImage(
            path=screenshot_path,
            width=screenshot_dimensions[0] if screenshot_dimensions is not None else None,
            height=screenshot_dimensions[1] if screenshot_dimensions is not None else None,
            content_type="image/png",
            source="browser_screenshot",
            clean=False,
        )
    else:
        primary_image = None

    if primary_image is not None:
        _record_primary_image(nav_result, primary_image, clean_image_error)

    sv_coords_from_url = extract_coordinates_from_url(current_url)
    if sv_coords_from_url:
        resolved_coords = CoordinatePair(lat=sv_coords_from_url[0], lng=sv_coords_from_url[1])

    orientation_tokens = extract_orientation_from_url(current_url)
    orientation = StreetViewOrientation(
        heading=orientation_tokens.get("heading"),
        pitch=orientation_tokens.get("pitch"),
        fov=orientation_tokens.get("fov"),
    )

    screenshot = (
        StreetViewScreenshot(
            path=screenshot_path,
            width=viewport.width if viewport else None,
            height=viewport.height if viewport else None,
        )
        if screenshot_path is not None
        else None
    )

    extracted = StreetViewExtracted(
        requested_location=request.location,
        requested_pano=request.pano,
        requested_heading=request.heading,
        requested_pitch=request.pitch,
        requested_fov=request.fov,
        location_resolution=location_resolution,
        requested_viewpoint=viewpoint,
        resolved_url=current_url,
        resolved_coordinates=resolved_coords,
        orientation=orientation,
        image=primary_image,
        screenshot=screenshot,
        unsupported_api_fields=unsupported,
    )

    confidence_notes: list[str] = []
    if "map_action=pano" not in current_url and "streetview" not in current_url.lower():
        confidence_notes.append("Resolved URL may not be a Street View panorama.")
    if clean_image is None:
        note = "Google Maps web did not expose a usable clean panorama renderer."
        if screenshot_path is not None:
            note += " Returned the UI screenshot."
        else:
            note += " No fallback UI screenshot was captured."
        if clean_image_error is not None:
            note += f" Renderer error: {clean_image_error}"
        confidence_notes.append(note)

    return ApiEnvelope(
        ok=primary_image is not None,
        source="google_maps_web",
        request=request.model_dump(),
        maps_url=sv_url,
        extracted=extracted,
        artifacts=artifact_set_from_navigation(nav_result),
        confidence=Confidence(
            overall=("low" if primary_image is None else "medium") if confidence_notes else "high",
            notes=confidence_notes,
        ),
    )


def _try_parse_latlng(text: str) -> tuple[float, float] | None:
    import re

    match = re.match(r"^(-?\d+\.?\d*),\s*(-?\d+\.?\d*)$", text.strip())
    if match:
        return float(match.group(1)), float(match.group(2))
    return None


def _record_primary_image(
    navigation: dict[str, object],
    image: StreetViewImage,
    renderer_error: str | None,
) -> None:
    response_path_value = navigation.get("response_path")
    if response_path_value is None:
        return
    path = Path(str(response_path_value))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return
        artifacts = payload.setdefault("artifacts", {})
        if isinstance(artifacts, dict):
            artifacts["street_view_image"] = navigation.get("street_view_image")
        payload["primary_image"] = image.model_dump()
        payload["renderer_error"] = renderer_error
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except (OSError, ValueError, TypeError):
        return


def _error_envelope(
    request: StreetViewRequest,
    message: str,
    unsupported: list[UnsupportedField],
) -> ApiEnvelope[StreetViewExtracted]:
    return ApiEnvelope(
        ok=False,
        source="google_maps_web",
        request=request.model_dump(),
        maps_url=None,
        extracted=StreetViewExtracted(
            requested_location=request.location,
            requested_pano=request.pano,
            requested_heading=request.heading,
            requested_pitch=request.pitch,
            requested_fov=request.fov,
            unsupported_api_fields=unsupported,
        ),
        artifacts=ArtifactSet(),
        confidence=Confidence(overall="low", notes=[message]),
    )
