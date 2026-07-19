from __future__ import annotations

import re
from collections.abc import Iterator

from free_gmaps_api.web.observations import (
    ObservedCoordinates,
    ObservedPlace,
    ObservedRoute,
)

_PLACE_ID_RE = re.compile(r"^ChI[A-Za-z0-9_-]{12,}$")
_ADDRESS_RE = re.compile(
    r"\b\d+\s+[^\n,]{2,80}?\s+(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|"
    r"Ln|Lane|Way|Pl|Place|Pkwy|Parkway)\b[^\n]{0,100}",
    re.IGNORECASE,
)
_RATING_RE = re.compile(r"^([1-5](?:\.\d)?)\s*(?:\(([\d,]+)\))?$")
_DURATION_RE = re.compile(
    r"^(?:(?:\d+\s*(?:hr|hour)s?)\s*)?(?:\d+\s*(?:min|minute)s?)$", re.IGNORECASE
)
_DISTANCE_RE = re.compile(
    r"^\d+(?:\.\d+)?\s*(?:ft|feet|mi|mile|miles|km|kilometer|kilometers|m|meter|meters)$",
    re.IGNORECASE,
)
_STOP_WORDS = frozenset({"the", "in", "at", "of", "wa", "usa", "us", "place", "id"})
_UI_LABELS = frozenset(
    {
        "about",
        "directions",
        "nearby",
        "overview",
        "save",
        "see photos",
        "send to phone",
        "share",
    }
)
_CHILD_SECTION_MARKERS = frozenset(
    {"at this place", "people also search for", "similar places", "nearby places"}
)
_MAX_DEPTH = 64
_MAX_NODES = 10_000
_MAX_SCALARS = 50_000
_MAX_STRING_CHARS = 2_000_000


def parse_search_place(
    payload: object,
    *,
    query: str | None,
    expected_place_id: str | None = None,
    expected_coordinates: ObservedCoordinates | None = None,
) -> ObservedPlace | None:
    """Return the smallest record tied to the requested identity.

    Maps payloads are undocumented nested arrays.  This parser deliberately
    avoids fixed offsets: a candidate container must contain the expected
    official ID, or both query identity tokens and place evidence such as an
    address or coordinates.  Arbitrary coordinates elsewhere in the response
    are therefore never accepted merely because they look geographic.
    """

    query_tokens = _identity_tokens(query)
    nodes = _collect_containers(payload)
    if nodes is None:
        return None
    candidates: list[tuple[int, int, ObservedPlace]] = []
    for node in nodes:
        direct_strings = _direct_strings(node)
        if not direct_strings:
            continue
        ids = [value for value in direct_strings if _PLACE_ID_RE.fullmatch(value)]
        id_match = expected_place_id is not None and expected_place_id in ids
        if expected_place_id is not None and not id_match:
            continue
        name, overlap = _best_identity_string(direct_strings, query_tokens)
        address = _record_address(node)
        coordinates = _record_coordinate(
            node,
            query_tokens=query_tokens,
            expected_place_id=expected_place_id,
        )
        coordinate_match = (
            coordinates is not None
            and expected_coordinates is not None
            and abs(coordinates.lat - expected_coordinates.lat) <= 0.01
            and abs(coordinates.lng - expected_coordinates.lng) <= 0.01
        )
        token_threshold = min(2, len(query_tokens))
        query_match = bool(query_tokens) and overlap >= token_threshold
        if (
            not id_match
            and not coordinate_match
            and not (query_match and (address is not None or coordinates is not None))
        ):
            continue
        canonical_url = _record_url(node, query_tokens=query_tokens)
        official_id = expected_place_id if id_match else (ids[0] if ids else None)
        basis = tuple(
            label
            for label, matched in (
                ("official_place_id", id_match),
                ("requested_coordinates", coordinate_match),
                ("query_tokens", query_match),
                ("address", address is not None),
                ("coordinates", coordinates is not None),
            )
            if matched
        )
        score = (
            (8 if id_match else 0)
            + (8 if coordinate_match else 0)
            + overlap
            + (2 if address else 0)
            + (2 if coordinates else 0)
        )
        candidates.append(
            (
                score,
                -_scalar_count(node),
                ObservedPlace(
                    name=name,
                    address=address,
                    coordinates=coordinates,
                    official_place_id=official_id,
                    canonical_url=canonical_url,
                    match_basis=basis,
                ),
            )
        )
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]


def parse_primary_place_card(text: str, *, query: str | None) -> ObservedPlace | None:
    """Parse only the selected place card, stopping before child businesses."""

    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    lines: list[str] = []
    for line in raw_lines:
        if line.casefold() in _CHILD_SECTION_MARKERS:
            break
        if _human_text(line):
            lines.append(line)
    if not lines:
        return None

    query_tokens = _identity_tokens(query)
    name, overlap = _best_identity_string(lines, query_tokens)
    token_threshold = min(2, len(query_tokens))
    if query_tokens and overlap < token_threshold:
        return None
    if name is None:
        name = next(
            (
                line
                for line in lines
                if line.casefold() not in _UI_LABELS
                and not _RATING_RE.fullmatch(line)
                and _ADDRESS_RE.search(line) is None
            ),
            None,
        )
    category = next(
        (
            line.split("·", 1)[0].strip()
            for line in lines
            if "·" in line and line.split("·", 1)[0].strip()
        ),
        None,
    )
    rating: float | None = None
    review_count: int | None = None
    for line in lines:
        match = _RATING_RE.fullmatch(line.replace(" ", ""))
        if match:
            rating = float(match.group(1))
            review_count = int(match.group(2).replace(",", "")) if match.group(2) else None
            break
    address = _first_address(lines)
    if not any((name, address, rating, category)):
        return None
    return ObservedPlace(
        name=name,
        address=address,
        category=category,
        rating=rating,
        review_count=review_count,
        match_basis=("visible_primary_card",) if overlap else ("visible_text",),
    )


def parse_directions_routes(
    payload: object, *, origin: str, destination: str
) -> list[ObservedRoute]:
    """Return request-anchored routes whose fields share one record container."""

    nodes = _collect_containers(payload)
    if nodes is None or not _matches_request_identity(payload, origin, destination):
        return []
    parents = _container_parents(nodes)
    routes: list[ObservedRoute] = []
    for node in nodes:
        parent = parents.get(id(node))
        if parent is None or not _matches_request_identity(parent, origin, destination):
            continue
        slots = _route_record_slots(node)
        if _record_repeats_request_identity(slots, origin, destination):
            continue
        for index in range(len(slots) - 1):
            first = slots[index]
            second = slots[index + 1]
            if first is None or second is None:
                continue
            if _DURATION_RE.fullmatch(first) and _DISTANCE_RE.fullmatch(second):
                duration, distance = first, second
            elif _DISTANCE_RE.fullmatch(first) and _DURATION_RE.fullmatch(second):
                duration, distance = second, first
            else:
                continue
            context_index, context = _route_context(slots, index, index + 1)
            if context is None:
                continue
            label = context if context.casefold().startswith("via ") else f"via {context}"
            summary = _route_summary(slots, context_index)
            route = ObservedRoute(duration, distance, label, summary)
            if route not in routes:
                routes.append(route)
    return routes


def _route_record_slots(value: object) -> list[str | None]:
    """Preserve record slots while allowing Google's one-string wrapper lists."""

    children = (
        value
        if isinstance(value, list)
        else list(value.values())
        if isinstance(value, dict)
        else []
    )
    slots: list[str | None] = []
    for child in children:
        if isinstance(child, str):
            slots.append(child.strip() or None)
            continue
        if isinstance(child, (list, dict)):
            strings = [item.strip() for item in _direct_strings(child) if item.strip()]
            slots.append(strings[0] if len(strings) == 1 else None)
            continue
        slots.append(None)
    return slots


def _record_repeats_request_identity(
    slots: list[str | None], origin: str, destination: str
) -> bool:
    """Do not treat a request-envelope container as an individual route record."""

    strings = [value for value in slots if value is not None]
    return all(
        any(
            len(_identity_tokens(value) & _identity_tokens(expected))
            >= min(2, len(_identity_tokens(expected)))
            for value in strings
        )
        for expected in (origin, destination)
    )


def _route_context(
    slots: list[str | None], first_index: int, second_index: int
) -> tuple[int, str | None]:
    for index in (first_index - 1, second_index + 1):
        if index < 0 or index >= len(slots):
            continue
        value = slots[index]
        if (
            value is not None
            and not _DURATION_RE.fullmatch(value)
            and not _DISTANCE_RE.fullmatch(value)
        ):
            return index, value
    return -1, None


def _route_summary(slots: list[str | None], context_index: int) -> str | None:
    next_index = context_index + 1
    if next_index >= len(slots):
        return None
    value = slots[next_index]
    if value is None or _DURATION_RE.fullmatch(value) or _DISTANCE_RE.fullmatch(value):
        return None
    return value


def _containers(value: object) -> Iterator[object]:
    if isinstance(value, (list, dict)):
        yield value
        children = value if isinstance(value, list) else value.values()
        for child in children:
            yield from _containers(child)


def _collect_containers(value: object) -> list[object] | None:
    containers: list[object] = []
    stack: list[tuple[object, int]] = [(value, 0)]
    scalar_count = 0
    string_chars = 0
    while stack:
        current, depth = stack.pop()
        if depth > _MAX_DEPTH:
            return None
        if isinstance(current, (list, dict)):
            containers.append(current)
            if len(containers) > _MAX_NODES:
                return None
            children = list(current if isinstance(current, list) else current.values())
            stack.extend((child, depth + 1) for child in reversed(children))
        else:
            scalar_count += 1
            if scalar_count > _MAX_SCALARS:
                return None
            if isinstance(current, str):
                string_chars += len(current)
                if string_chars > _MAX_STRING_CHARS:
                    return None
    return containers


def _direct_strings(value: object) -> list[str]:
    children = (
        value if isinstance(value, list) else value.values() if isinstance(value, dict) else []
    )
    return [child for child in children if isinstance(child, str)]


def _record_address(value: object) -> str | None:
    direct = _first_address(_direct_strings(value))
    if direct is not None:
        return direct
    for child in _direct_containers(value):
        child_address = _first_address(_direct_strings(child))
        if child_address is not None:
            return child_address
    return None


def _record_coordinate(
    value: object,
    *,
    query_tokens: set[str],
    expected_place_id: str | None,
) -> ObservedCoordinates | None:
    direct = _coordinate_in_sequence(value)
    if direct is not None:
        return direct
    for child in _direct_containers(value):
        strings = _direct_strings(child)
        # A nested container with its own human identity is another record,
        # even when that identity shares tokens with the selected parent.
        # Coordinate wrappers in observed Maps payloads are numeric-only.
        if strings:
            continue
        if _crosses_foreign_record(
            strings, query_tokens=query_tokens, expected_place_id=expected_place_id
        ):
            continue
        coordinate = _record_coordinate(
            child,
            query_tokens=query_tokens,
            expected_place_id=expected_place_id,
        )
        if coordinate is not None:
            return coordinate
    return None


def _record_url(value: object, *, query_tokens: set[str]) -> str | None:
    for candidate in _direct_strings(value):
        if "google." in candidate and "/maps/" in candidate:
            return candidate
    for child in _direct_containers(value):
        strings = _direct_strings(child)
        if _crosses_foreign_record(strings, query_tokens=query_tokens, expected_place_id=None):
            continue
        for candidate in strings:
            if "google." in candidate and "/maps/" in candidate:
                return candidate
    return None


def _direct_containers(value: object) -> list[object]:
    children = (
        value if isinstance(value, list) else value.values() if isinstance(value, dict) else []
    )
    return [child for child in children if isinstance(child, (list, dict))]


def _container_parents(nodes: list[object]) -> dict[int, object]:
    parents: dict[int, object] = {}
    for node in nodes:
        for child in _direct_containers(node):
            parents[id(child)] = node
    return parents


def _crosses_foreign_record(
    strings: list[str], *, query_tokens: set[str], expected_place_id: str | None
) -> bool:
    for value in strings:
        if expected_place_id is not None and _PLACE_ID_RE.fullmatch(value):
            return value != expected_place_id
        if _ADDRESS_RE.search(value) or value.startswith(("http://", "https://")):
            continue
        normalized = value.casefold().strip()
        if normalized in {"photo", "photos", "searchresult.type_tourist_destination"}:
            continue
        tokens = _identity_tokens(value)
        if tokens and not (tokens & query_tokens):
            return True
    return False


def _coordinate_in_sequence(value: object) -> ObservedCoordinates | None:
    if not isinstance(value, list):
        return None
    numbers = [
        item if isinstance(item, (int, float)) and not isinstance(item, bool) else None
        for item in value
    ]
    for first, second in zip(numbers, numbers[1:], strict=False):
        if first is None or second is None:
            continue
        if -90 <= first <= 90 and -180 <= second <= 180 and (abs(first) > 1 or abs(second) > 1):
            return ObservedCoordinates(float(first), float(second))
        if -180 <= first <= 180 and -90 <= second <= 90 and abs(first) > 90:
            return ObservedCoordinates(float(second), float(first))
    return None


def _matches_request_identity(payload: object, origin: str, destination: str) -> bool:
    payload_strings = list(_strings(payload))
    for expected in (origin, destination):
        expected_tokens = _identity_tokens(expected)
        threshold = min(2, len(expected_tokens))
        if not expected_tokens or not any(
            len(_identity_tokens(value) & expected_tokens) >= threshold for value in payload_strings
        ):
            return False
    return True


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _first_coordinate(value: object) -> ObservedCoordinates | None:
    for node in _containers(value):
        if not isinstance(node, list):
            continue
        numbers = [
            item if isinstance(item, (int, float)) and not isinstance(item, bool) else None
            for item in node
        ]
        for first, second in zip(numbers, numbers[1:], strict=False):
            if first is None or second is None:
                continue
            if -90 <= first <= 90 and -180 <= second <= 180 and (abs(first) > 1 or abs(second) > 1):
                return ObservedCoordinates(float(first), float(second))
            if -180 <= first <= 180 and -90 <= second <= 90 and abs(first) > 90:
                return ObservedCoordinates(float(second), float(first))
    return None


def _first_address(strings: list[str]) -> str | None:
    for value in strings:
        match = _ADDRESS_RE.search(value)
        if match:
            return match.group(0).strip()
    return None


def _best_identity_string(strings: list[str], query_tokens: set[str]) -> tuple[str | None, int]:
    choices: list[tuple[int, int, str]] = []
    for value in strings:
        if len(value) > 200 or value.startswith(("http://", "https://")):
            continue
        if _PLACE_ID_RE.fullmatch(value) or _ADDRESS_RE.search(value):
            continue
        tokens = _identity_tokens(value)
        overlap = len(tokens & query_tokens)
        if overlap:
            choices.append((overlap, -len(value), value))
    if not choices:
        return None, 0
    overlap, _, value = max(choices)
    return value, overlap


def _identity_tokens(value: str | None) -> set[str]:
    if not value:
        return set()
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 1 and token not in _STOP_WORDS
    }


def _human_text(value: str) -> bool:
    return any(character.isalnum() for character in value) and not (
        value.startswith("[") or value.startswith("{")
    )


def _scalar_count(value: object) -> int:
    if isinstance(value, list):
        return sum(_scalar_count(item) for item in value)
    if isinstance(value, dict):
        return sum(_scalar_count(item) for item in value.values())
    return 1
