from __future__ import annotations

import re
import uuid

from free_gmaps_api.browser.artifacts import artifact_set_from_navigation
from free_gmaps_api.browser.extract import (
    extract_coordinates_from_url,
    extract_decimal_coords_from_text,
    extract_dms_from_text,
    extract_plus_code_from_text,
)
from free_gmaps_api.browser.session import BrowserSession, CapturedResponse, ResponseCapture
from free_gmaps_api.contracts.envelope import ApiEnvelope, ArtifactSet, Confidence, UnsupportedField
from free_gmaps_api.contracts.extracted import (
    CoordinatePair,
    GeocodeExtracted,
    ReverseGeocodeExtracted,
)
from free_gmaps_api.contracts.requests import GeocodeRequest, ReverseGeocodeRequest
from free_gmaps_api.maps_urls.search import build_search_url
from free_gmaps_api.support.matrix import get_unsupported_fields
from free_gmaps_api.web.observations import ObservedCoordinates, ObservedPlace
from free_gmaps_api.web.parsers import parse_primary_place_card, parse_search_place

_SEARCH_CAPTURE = ResponseCapture(
    name="maps-search",
    url_pattern=re.compile(r"https://www\.google\.com/search\?.*\btbm=map(?:&|$).*"),
)


async def run_geocode(
    request: GeocodeRequest,
    session: BrowserSession,
) -> ApiEnvelope[GeocodeExtracted]:
    request_id = uuid.uuid4().hex
    unsupported = get_unsupported_fields("geocode", request)

    query = request.address or (f"place_id:{request.place_id}" if request.place_id else None)
    if not query:
        return _geocode_error(request, "Must provide 'address' or 'place_id'.", unsupported)

    search_url = build_search_url(query, place_id=request.place_id)
    try:
        nav_result = await session.navigate(
            search_url, request_id=request_id, response_captures=(_SEARCH_CAPTURE,)
        )
    except Exception as exc:
        return _geocode_error(request, str(exc), unsupported)

    current_url = str(nav_result["current_url"])
    raw_text = str(nav_result.get("raw_visible_text", ""))

    observation = _structured_place(nav_result, query=query, place_id=request.place_id)
    visible = parse_primary_place_card(raw_text, query=query)
    if request.place_id is not None and observation is None:
        visible = None
    coords_tuple = extract_coordinates_from_url(current_url)
    coords: CoordinatePair | None = None
    if observation is not None and observation.coordinates is not None:
        coords = CoordinatePair(lat=observation.coordinates.lat, lng=observation.coordinates.lng)
    elif visible is not None and coords_tuple:
        coords = CoordinatePair(lat=coords_tuple[0], lng=coords_tuple[1])

    plus_code = extract_plus_code_from_text(raw_text)
    display_name = (
        observation.name if observation is not None else (visible.name if visible else None)
    )

    extracted = GeocodeExtracted(
        input=query,
        input_type="address" if request.address else "place_id",
        display_name=display_name,
        formatted_address=(
            observation.address
            if observation is not None
            else (visible.address if visible else None)
        ),
        coordinates=coords,
        plus_code=plus_code,
        place_url=(observation.canonical_url if observation else None) or current_url,
        unsupported_api_fields=unsupported,
    )

    ok = coords is not None and (observation is not None or visible is not None)
    confidence_notes: list[str] = []
    if not ok:
        confidence_notes.append("Coordinates could not be tied to the selected place identity.")

    return ApiEnvelope(
        ok=ok,
        source="google_maps_web",
        request=request.model_dump(),
        maps_url=search_url,
        extracted=extracted,
        artifacts=artifact_set_from_navigation(nav_result),
        confidence=Confidence(overall="medium" if ok else "low", notes=confidence_notes),
    )


async def run_reverse_geocode(
    request: ReverseGeocodeRequest,
    session: BrowserSession,
) -> ApiEnvelope[ReverseGeocodeExtracted]:
    request_id = uuid.uuid4().hex
    unsupported = get_unsupported_fields("reverse-geocode", request)

    search_url = build_search_url(request.latlng)
    try:
        nav_result = await session.navigate(
            search_url, request_id=request_id, response_captures=(_SEARCH_CAPTURE,)
        )
    except Exception as exc:
        return _reverse_error(request, str(exc), unsupported)

    raw_text = str(nav_result.get("raw_visible_text", ""))
    current_url = str(nav_result["current_url"])

    dms = extract_dms_from_text(raw_text)
    decimal = extract_decimal_coords_from_text(raw_text)
    plus_code = extract_plus_code_from_text(raw_text)
    lat, lng = (float(part.strip()) for part in request.latlng.split(",", 1))
    observation = _structured_place(
        nav_result,
        query=request.latlng,
        place_id=None,
        expected_coordinates=ObservedCoordinates(lat, lng),
    )
    nearest = observation.address if observation is not None else None
    if nearest is None:
        nearest = _extract_nearest_address(raw_text)
    ok = nearest is not None

    extracted = ReverseGeocodeExtracted(
        input_coordinates=request.latlng,
        display_coordinates_dms=dms,
        display_coordinates_decimal=decimal,
        plus_code=plus_code,
        nearest_address_or_place=nearest,
        place_url=(observation.canonical_url if observation else None) or current_url,
        unsupported_api_fields=unsupported,
    )

    return ApiEnvelope(
        ok=ok,
        source="google_maps_web",
        request=request.model_dump(),
        maps_url=search_url,
        extracted=extracted,
        artifacts=artifact_set_from_navigation(nav_result),
        confidence=Confidence(
            overall="medium" if ok else "low",
            notes=[]
            if ok
            else ["No address-bearing place record matched the requested coordinates."],
        ),
    )


def _structured_place(
    nav_result: dict[str, object],
    *,
    query: str | None,
    place_id: str | None,
    expected_coordinates: ObservedCoordinates | None = None,
) -> ObservedPlace | None:
    import json

    captures = nav_result.get("captured_responses")
    if not isinstance(captures, list):
        return None
    for captured in captures:
        if not isinstance(captured, CapturedResponse) or captured.name != "maps-search":
            continue
        try:
            payload = json.loads(captured.body.decode("utf-8").removeprefix(")]}'\n"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        observation = parse_search_place(
            payload,
            query=query,
            expected_place_id=place_id,
            expected_coordinates=expected_coordinates,
        )
        if observation is not None:
            return observation
    return None


def _extract_nearest_address(text: str) -> str | None:
    match = re.search(
        r"\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:St|Ave|Blvd|Rd|Dr|Ln|Way|Pl)\b[^,\n]*", text
    )
    if match:
        return match.group(0).strip()
    return None


def _geocode_error(
    request: GeocodeRequest,
    message: str,
    unsupported: list[UnsupportedField],
) -> ApiEnvelope[GeocodeExtracted]:
    return ApiEnvelope(
        ok=False,
        source="google_maps_web",
        request=request.model_dump(),
        maps_url=None,
        extracted=GeocodeExtracted(
            input=request.address or request.place_id,
            input_type="address" if request.address else "place_id",
            unsupported_api_fields=unsupported,
        ),
        artifacts=ArtifactSet(),
        confidence=Confidence(overall="low", notes=[message]),
    )


def _reverse_error(
    request: ReverseGeocodeRequest,
    message: str,
    unsupported: list[UnsupportedField],
) -> ApiEnvelope[ReverseGeocodeExtracted]:
    return ApiEnvelope(
        ok=False,
        source="google_maps_web",
        request=request.model_dump(),
        maps_url=None,
        extracted=ReverseGeocodeExtracted(
            input_coordinates=request.latlng,
            unsupported_api_fields=unsupported,
        ),
        artifacts=ArtifactSet(),
        confidence=Confidence(overall="low", notes=[message]),
    )
