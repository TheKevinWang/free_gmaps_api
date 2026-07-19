from __future__ import annotations

import re
import uuid

from free_gmaps_api.browser.artifacts import artifact_set_from_navigation
from free_gmaps_api.browser.extract import (
    extract_coordinates_from_url,
    extract_place_url_ids,
    extract_plus_code_from_text,
)
from free_gmaps_api.browser.session import BrowserSession, CapturedResponse, ResponseCapture
from free_gmaps_api.contracts.envelope import ApiEnvelope, ArtifactSet, Confidence, UnsupportedField
from free_gmaps_api.contracts.extracted import CoordinatePair, PlaceExtracted
from free_gmaps_api.contracts.requests import PlaceDetailsRequest, PlaceSearchRequest
from free_gmaps_api.maps_urls.search import build_search_url
from free_gmaps_api.maps_urls.security import validate_google_maps_url
from free_gmaps_api.support.matrix import get_unsupported_fields
from free_gmaps_api.web.observations import ObservedPlace
from free_gmaps_api.web.parsers import parse_primary_place_card, parse_search_place

_SEARCH_CAPTURE = ResponseCapture(
    name="maps-search",
    url_pattern=re.compile(r"https://www\.google\.com/search\?.*\btbm=map(?:&|$).*"),
)
_PLACE_CAPTURE = ResponseCapture(
    name="maps-place",
    url_pattern=re.compile(r"https://www\.google\.com/maps/preview/place\?.*"),
)
_PLACE_CAPTURES = (_SEARCH_CAPTURE, _PLACE_CAPTURE)

# Unicode Private Use Area: Material Design icon glyphs render here and must
# not be mistaken for human-readable text (e.g. U+E5D2 = search icon).
_PUA_START = ""
_PUA_END = ""


async def run_place_search(
    request: PlaceSearchRequest,
    session: BrowserSession,
) -> ApiEnvelope[PlaceExtracted]:
    request_id = uuid.uuid4().hex
    unsupported = get_unsupported_fields("place-search", request)

    search_url = build_search_url(request.query)
    try:
        nav_result = await session.navigate(
            search_url, request_id=request_id, response_captures=_PLACE_CAPTURES
        )
    except Exception as exc:
        return _place_error(request.model_dump(), str(exc), unsupported, query=request.query)

    return _build_place_envelope(
        request.model_dump(), nav_result, search_url, request.query, unsupported
    )


async def run_place_details(
    request: PlaceDetailsRequest,
    session: BrowserSession,
) -> ApiEnvelope[PlaceExtracted]:
    request_id = uuid.uuid4().hex
    unsupported = get_unsupported_fields("place-details", request)

    if request.maps_url:
        try:
            url = validate_google_maps_url(request.maps_url)
        except ValueError as exc:
            return _place_error(request.model_dump(), str(exc), unsupported)
    elif request.query:
        url = build_search_url(request.query, place_id=request.place_id)
    elif request.place_id:
        url = build_search_url(f"place_id:{request.place_id}", place_id=request.place_id)
    else:
        return _place_error(
            request.model_dump(), "Must provide place_id, maps_url, or query.", unsupported
        )

    try:
        nav_result = await session.navigate(
            url, request_id=request_id, response_captures=_PLACE_CAPTURES
        )
    except Exception as exc:
        return _place_error(request.model_dump(), str(exc), unsupported)

    return _build_place_envelope(
        request.model_dump(),
        nav_result,
        url,
        request.query or request.place_id,
        unsupported,
    )


def _build_place_envelope(
    request_dict: dict[str, object],
    nav_result: dict[str, object],
    maps_url: str,
    query: str | None,
    unsupported: list[UnsupportedField],
) -> ApiEnvelope[PlaceExtracted]:
    current_url = str(nav_result["current_url"])
    raw_text = str(nav_result.get("raw_visible_text", ""))

    expected_place_id = request_dict.get("place_id")
    observation = _structured_place(
        nav_result,
        query=query,
        place_id=str(expected_place_id) if expected_place_id else None,
    )
    visible = parse_primary_place_card(raw_text, query=query)
    if expected_place_id and observation is None:
        visible = None

    coords_tuple = extract_coordinates_from_url(current_url)
    coords: CoordinatePair | None = None
    if observation is not None and observation.coordinates is not None:
        coords = CoordinatePair(lat=observation.coordinates.lat, lng=observation.coordinates.lng)
    elif visible is not None and coords_tuple:
        coords = CoordinatePair(lat=coords_tuple[0], lng=coords_tuple[1])

    url_ids = extract_place_url_ids(current_url)
    plus_code = extract_plus_code_from_text(raw_text)

    merged = _merge_observations(observation, visible)

    extracted = PlaceExtracted(
        query=query,
        name=merged.name if merged else None,
        category=merged.category if merged else None,
        rating=merged.rating if merged else None,
        review_count=merged.review_count if merged else None,
        address=merged.address if merged else None,
        plus_code=plus_code,
        place_detail_url=(merged.canonical_url if merged else None) or current_url,
        coordinates=coords,
        official_place_id=merged.official_place_id if merged else None,
        observed_maps_url_ids=url_ids,
        id_provenance="url_token" if url_ids else None,
        unsupported_api_fields=unsupported,
    )

    return ApiEnvelope(
        ok=bool(merged and (merged.name or merged.address or coords)),
        source="google_maps_web",
        request=request_dict,
        maps_url=maps_url,
        extracted=extracted,
        artifacts=artifact_set_from_navigation(nav_result),
        confidence=Confidence(
            overall="medium" if merged and (merged.name or merged.address or coords) else "low",
            notes=[]
            if merged and (merged.name or merged.address or coords)
            else ["No credible selected-place identity was observed."],
        ),
    )


_UI_LABELS = frozenset(
    {
        "see photos",
        "overview",
        "about",
        "directions",
        "save",
        "nearby",
        "send to phone",
        "share",
    }
)
_STANDALONE_NUMBER_RE = re.compile(r"^\d+\.?\d*$")


def _parse_place_card(
    text: str,
) -> tuple[str | None, str | None, float | None, int | None, str | None]:
    name: str | None = None
    category: str | None = None
    rating: float | None = None
    review_count: int | None = None
    address: str | None = None

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and _is_readable_text(line.strip())
    ]

    for line in lines:
        if line.lower() in _UI_LABELS:
            continue
        if _STANDALONE_NUMBER_RE.match(line):
            continue
        name = line
        break

    for line in lines:
        if line.endswith("·") or line.endswith("⋅"):
            category = line.rstrip("·⋅").strip()
            break

    rating_match = re.search(r"\b([1-5]\.?\d?)\s*\([\d,]+\)", text)
    if rating_match:
        rating = float(rating_match.group(1))
        reviews_match = re.search(r"\(([\d,]+)\)", rating_match.group(0))
        if reviews_match:
            review_count = int(reviews_match.group(1).replace(",", ""))

    addr_match = re.search(
        r"\d+\s+[\w\s]+(?:St|Ave|Blvd|Rd|Dr|Ln|Way|Pl|Pkwy)\b[^,\n]*(?:,\s*[^,\n]+)*", text
    )
    if addr_match:
        address = addr_match.group(0).strip()

    return name, category, rating, review_count, address


def _structured_place(
    nav_result: dict[str, object], *, query: str | None, place_id: str | None
) -> ObservedPlace | None:
    import json

    captures = nav_result.get("captured_responses")
    if not isinstance(captures, list):
        return None
    for captured in captures:
        if not isinstance(captured, CapturedResponse) or captured.name not in {
            "maps-search",
            "maps-place",
        }:
            continue
        try:
            payload = json.loads(captured.body.decode("utf-8").removeprefix(")]}'\n"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        observation = parse_search_place(payload, query=query, expected_place_id=place_id)
        if observation is not None:
            return observation
    return None


def _merge_observations(
    structured: ObservedPlace | None, visible: ObservedPlace | None
) -> ObservedPlace | None:
    if structured is None:
        return visible
    if visible is None:
        return structured
    return ObservedPlace(
        name=structured.name or visible.name,
        address=structured.address or visible.address,
        coordinates=structured.coordinates,
        official_place_id=structured.official_place_id,
        canonical_url=structured.canonical_url,
        category=structured.category or visible.category,
        rating=structured.rating if structured.rating is not None else visible.rating,
        review_count=(
            structured.review_count if structured.review_count is not None else visible.review_count
        ),
        match_basis=structured.match_basis + visible.match_basis,
    )


def _is_readable_text(line: str) -> bool:
    return any(not (_PUA_START <= c <= _PUA_END) for c in line)


def _place_error(
    request_dict: dict[str, object],
    message: str,
    unsupported: list[UnsupportedField],
    query: str | None = None,
) -> ApiEnvelope[PlaceExtracted]:
    return ApiEnvelope(
        ok=False,
        source="google_maps_web",
        request=request_dict,
        maps_url=None,
        extracted=PlaceExtracted(
            query=query,
            unsupported_api_fields=unsupported,
        ),
        artifacts=ArtifactSet(),
        confidence=Confidence(overall="low", notes=[message]),
    )
