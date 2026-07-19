from __future__ import annotations

import asyncio
import contextlib
import re
import uuid
from typing import Any, Literal

from free_gmaps_api.browser.artifacts import artifact_set_from_navigation
from free_gmaps_api.browser.session import BrowserSession
from free_gmaps_api.contracts.envelope import ApiEnvelope, ArtifactSet, Confidence, UnsupportedField
from free_gmaps_api.contracts.extracted import (
    DirectionsExtracted,
    DirectionsRoute,
    DirectionsRouteStep,
)
from free_gmaps_api.contracts.requests import DirectionsRequest
from free_gmaps_api.maps_urls.directions import build_directions_url
from free_gmaps_api.support.matrix import get_unsupported_fields

_DURATION_RE = re.compile(
    r"(?:(?P<hours>\d+)[ \t]*(?:hr|hour)s?[ \t]*)?"
    r"(?:(?P<minutes>\d+)[ \t]*(?:min|minute)s?)?",
    re.IGNORECASE,
)
_DISTANCE_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)[ \t]*"
    r"(?P<unit>ft|feet|mi|mile|miles|km|kilometer|kilometers|m|meter|meters)",
    re.IGNORECASE,
)
_DETAIL_SUMMARY_RE = re.compile(
    r"(?P<duration>[^()]+?)[ \t]*\((?P<distance>[^()]+)\)",
    re.IGNORECASE,
)
_ROUTE_DESCRIPTION_EXCLUSIONS = {
    "details",
    "preview",
    "options",
    "copy link",
    "add destination",
}
_DETAIL_STOP_LINES = {
    "sign in",
    "live traffic",
    "layers",
}


async def run_directions(
    request: DirectionsRequest,
    session: BrowserSession,
    *,
    include_details: bool = True,
) -> ApiEnvelope[DirectionsExtracted]:
    request_id = uuid.uuid4().hex
    unsupported = get_unsupported_fields("directions", request)

    maps_url = build_directions_url(
        origin=request.origin,
        destination=request.destination,
        travel_mode=request.travel_mode,
        waypoints=request.waypoints if request.waypoints else None,
        avoid=request.avoid if request.avoid else None,
    )

    try:
        nav_result = await session.navigate(
            maps_url,
            request_id=request_id,
            interaction=_open_directions_details if include_details else None,
            interaction_name="open-directions-details" if include_details else None,
        )
    except Exception as exc:
        return _directions_error(request, str(exc), unsupported)

    raw_text = str(nav_result.get("raw_visible_text", ""))
    details_text = _optional_text(nav_result.get("interaction_visible_text")) or ""
    interaction_error = _optional_text(nav_result.get("interaction_error"))

    all_routes = _parse_routes(raw_text)
    if not all_routes and details_text:
        all_routes = _parse_routes(details_text)
        if not all_routes:
            detail_route = _parse_detail_route(details_text)
            if detail_route is not None:
                all_routes = [detail_route]

    resolved_origin, resolved_destination = _parse_resolved_endpoints(details_text)
    steps = _parse_steps(details_text)
    selected = all_routes[0] if all_routes else None
    if selected is not None and steps:
        selected = selected.model_copy(update={"steps": steps})
        all_routes[0] = selected

    routes = all_routes if request.alternatives else all_routes[:1]
    warnings = _parse_warnings(raw_text)

    extracted = DirectionsExtracted(
        origin=request.origin,
        destination=request.destination,
        resolved_origin=resolved_origin,
        resolved_destination=resolved_destination,
        travel_mode=request.travel_mode,
        routes=routes,
        selected_route=selected,
        warnings=warnings,
        unsupported_api_fields=unsupported,
    )

    confidence_notes: list[str] = []
    confidence: Literal["high", "medium", "low"]
    if not all_routes:
        confidence_notes.append("No route data parsed from visible text.")
    if include_details and interaction_error is not None:
        confidence_notes.append(f"Directions Details interaction failed: {interaction_error}")
    elif include_details and selected is not None and not steps:
        confidence_notes.append("No route steps parsed from the Directions Details view.")

    if not all_routes:
        confidence = "low"
    elif confidence_notes:
        confidence = "medium"
    else:
        confidence = "high"

    return ApiEnvelope(
        ok=bool(all_routes),
        source="google_maps_web",
        request=request.model_dump(),
        maps_url=maps_url,
        extracted=extracted,
        artifacts=artifact_set_from_navigation(nav_result),
        confidence=Confidence(overall=confidence, notes=confidence_notes),
    )


async def _open_directions_details(page: Any) -> None:
    with contextlib.suppress(Exception):
        dismiss = await page.find("//button[@aria-label='Dismiss']", timeout=2)
        await dismiss.mouse_click("left")
        await asyncio.sleep(0.5)

    details = await page.find(
        "//button[.//span[normalize-space()='Details']]",
        timeout=5,
    )
    await details.click()


def _parse_routes(text: str) -> list[DirectionsRoute]:
    lines = _content_lines(text)
    routes: list[DirectionsRoute] = []
    seen: set[tuple[str, str, str | None]] = set()

    for index in range(1, len(lines)):
        duration = lines[index - 1]
        distance = lines[index]
        if _duration_seconds(duration) is None or _distance_meters(distance) is None:
            continue

        label: str | None = None
        description: str | None = None
        next_index = index + 1
        if next_index < len(lines) and lines[next_index].lower().startswith("via "):
            label = lines[next_index]
            next_index += 1
        if next_index < len(lines) and _is_route_description(lines[next_index]):
            description = lines[next_index]

        key = (duration.casefold(), distance.casefold(), label.casefold() if label else None)
        if key in seen:
            continue
        seen.add(key)

        route_warnings = (
            [description]
            if description is not None
            and any(term in description.casefold() for term in ("caution", "warning"))
            else []
        )
        routes.append(
            DirectionsRoute(
                summary=description,
                duration_text=duration,
                distance_text=distance,
                duration_seconds_approximate=_duration_seconds(duration),
                distance_meters_approximate=_distance_meters(distance),
                label=label,
                warnings=route_warnings,
            )
        )

    return routes


def _parse_detail_route(text: str) -> DirectionsRoute | None:
    lines = _content_lines(text)
    for index, line in enumerate(lines):
        match = _DETAIL_SUMMARY_RE.fullmatch(line)
        if match is None:
            continue
        duration = match.group("duration").strip()
        distance = match.group("distance").strip()
        if _duration_seconds(duration) is None or _distance_meters(distance) is None:
            continue
        label = (
            lines[index + 1]
            if index + 1 < len(lines) and lines[index + 1].lower().startswith("via ")
            else None
        )
        description_index = index + 2 if label is not None else index + 1
        description = (
            lines[description_index]
            if description_index < len(lines) and _is_route_description(lines[description_index])
            else None
        )
        return DirectionsRoute(
            summary=description,
            duration_text=duration,
            distance_text=distance,
            duration_seconds_approximate=_duration_seconds(duration),
            distance_meters_approximate=_distance_meters(distance),
            label=label,
        )
    return None


def _parse_resolved_endpoints(text: str) -> tuple[str | None, str | None]:
    origin: str | None = None
    destination: str | None = None
    for line in _content_lines(text):
        lower = line.casefold()
        if origin is None and lower.startswith("from "):
            origin = line[5:].strip() or None
        elif destination is None and lower.startswith("to "):
            destination = line[3:].strip() or None
    return origin, destination


def _parse_steps(text: str) -> list[DirectionsRouteStep]:
    lines = _content_lines(text)
    start_index = 0
    for index, line in enumerate(lines):
        if _DETAIL_SUMMARY_RE.fullmatch(line) is not None:
            start_index = index + 1
            break

    end_index = len(lines)
    for index in range(start_index, len(lines)):
        if lines[index].casefold() in _DETAIL_STOP_LINES:
            end_index = index
            break

    steps: list[DirectionsRouteStep] = []
    seen: set[tuple[str, str]] = set()
    for index in range(start_index + 1, end_index):
        distance = lines[index]
        distance_meters = _distance_meters(distance)
        if distance_meters is None:
            continue
        instruction = lines[index - 1]
        if not _is_step_instruction(instruction):
            continue
        key = (instruction.casefold(), distance.casefold())
        if key in seen:
            continue
        seen.add(key)
        steps.append(
            DirectionsRouteStep(
                instruction=instruction,
                distance_text=distance,
                distance_meters_approximate=distance_meters,
            )
        )
    return steps


def _duration_seconds(value: str) -> int | None:
    match = _DURATION_RE.fullmatch(value.strip())
    if match is None:
        return None
    hours_text = match.group("hours")
    minutes_text = match.group("minutes")
    if hours_text is None and minutes_text is None:
        return None
    return int(hours_text or 0) * 3600 + int(minutes_text or 0) * 60


def _distance_meters(value: str) -> int | None:
    match = _DISTANCE_RE.fullmatch(value.strip())
    if match is None:
        return None
    amount = float(match.group("value"))
    unit = match.group("unit").casefold()
    if unit in {"mi", "mile", "miles"}:
        multiplier = 1609.344
    elif unit in {"ft", "feet"}:
        multiplier = 0.3048
    elif unit in {"km", "kilometer", "kilometers"}:
        multiplier = 1000.0
    else:
        multiplier = 1.0
    return round(amount * multiplier)


def _content_lines(text: str) -> list[str]:
    return [
        line
        for raw_line in text.splitlines()
        if (line := raw_line.strip()) and re.search(r"[A-Za-z0-9]", line)
    ]


def _is_route_description(value: str) -> bool:
    lower = value.casefold()
    if lower in _ROUTE_DESCRIPTION_EXCLUSIONS:
        return False
    if lower.startswith(("search ", "explore ", "send directions")):
        return False
    return _duration_seconds(value) is None and _distance_meters(value) is None


def _is_step_instruction(value: str) -> bool:
    lower = value.casefold()
    if lower.startswith("via ") or lower in _DETAIL_STOP_LINES:
        return False
    if _DETAIL_SUMMARY_RE.fullmatch(value) is not None:
        return False
    return _duration_seconds(value) is None and _distance_meters(value) is None


def _parse_warnings(text: str) -> list[str]:
    warnings: list[str] = []
    for keyword in ("caution", "warning", "construction", "difficult"):
        for line in text.splitlines():
            if keyword.casefold() in line.casefold() and line.strip() not in warnings:
                warnings.append(line.strip())
    return warnings[:5]


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _directions_error(
    request: DirectionsRequest,
    message: str,
    unsupported: list[UnsupportedField],
) -> ApiEnvelope[DirectionsExtracted]:
    return ApiEnvelope(
        ok=False,
        source="google_maps_web",
        request=request.model_dump(),
        maps_url=None,
        extracted=DirectionsExtracted(
            origin=request.origin,
            destination=request.destination,
            travel_mode=request.travel_mode,
            unsupported_api_fields=unsupported,
        ),
        artifacts=ArtifactSet(),
        confidence=Confidence(overall="low", notes=[message]),
    )
