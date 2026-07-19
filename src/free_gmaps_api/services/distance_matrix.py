from __future__ import annotations

from free_gmaps_api.browser.session import BrowserSession
from free_gmaps_api.contracts.envelope import ApiEnvelope, ArtifactSet, Confidence
from free_gmaps_api.contracts.extracted import DistanceMatrixElement, DistanceMatrixExtracted
from free_gmaps_api.contracts.requests import DirectionsRequest, DistanceMatrixRequest
from free_gmaps_api.services.directions import run_directions
from free_gmaps_api.support.matrix import get_unsupported_fields


async def run_distance_matrix(
    request: DistanceMatrixRequest,
    session: BrowserSession,
) -> ApiEnvelope[DistanceMatrixExtracted]:
    unsupported = get_unsupported_fields("distance-matrix", request)
    elements: list[list[DistanceMatrixElement]] = []
    any_ok = False

    for origin in request.origins:
        row: list[DistanceMatrixElement] = []
        for destination in request.destinations:
            element = await _lookup_element(
                origin=origin,
                destination=destination,
                travel_mode=request.travel_mode,
                avoid=request.avoid,
                session=session,
            )
            row.append(element)
            if element.status == "ok":
                any_ok = True
        elements.append(row)

    extracted = DistanceMatrixExtracted(
        origins=request.origins,
        destinations=request.destinations,
        elements=elements,
        unsupported_api_fields=unsupported,
    )

    all_failed = not any_ok
    notes: list[str] = []
    if all_failed:
        notes.append("All matrix element lookups failed.")

    return ApiEnvelope(
        ok=not all_failed,
        source="google_maps_web",
        request=request.model_dump(),
        maps_url=None,
        extracted=extracted,
        artifacts=ArtifactSet(),
        confidence=Confidence(
            overall="low" if all_failed else "medium",
            notes=notes,
        ),
    )


async def _lookup_element(
    origin: str,
    destination: str,
    travel_mode: str,
    avoid: list[str],
    session: BrowserSession,
) -> DistanceMatrixElement:
    dir_request = DirectionsRequest(
        origin=origin,
        destination=destination,
        travel_mode=travel_mode,
        avoid=avoid,
    )
    try:
        result = await run_directions(dir_request, session, include_details=True)
    except Exception as exc:
        return DistanceMatrixElement(
            status="parse_error",
            confidence_notes=[str(exc)],
        )

    if not result.ok:
        return DistanceMatrixElement(
            status="not_supported",
            confidence_notes=result.confidence.notes,
        )

    selected = result.extracted.selected_route
    if not selected:
        return DistanceMatrixElement(
            status="zero_results",
            maps_url=result.maps_url,
            travel_mode=travel_mode,
            confidence_notes=result.confidence.notes,
        )

    return DistanceMatrixElement(
        status="ok",
        distance_text=selected.distance_text,
        duration_text=selected.duration_text,
        route_summary=selected.label or selected.summary,
        travel_mode=travel_mode,
        maps_url=result.maps_url,
        confidence_notes=result.confidence.notes,
    )
