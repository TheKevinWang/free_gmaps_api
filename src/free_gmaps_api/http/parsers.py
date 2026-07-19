from __future__ import annotations

import json
import re
from collections.abc import Iterator


class PayloadParseError(ValueError):
    """An internal Maps payload was absent, malformed, or too different to trust."""


def parse_xssi_json(body: str) -> object:
    text = body.lstrip()
    if text.startswith(")]}'"):
        newline = text.find("\n")
        if newline < 0:
            raise PayloadParseError("Anti-XSSI prefix was not followed by JSON.")
        text = text[newline + 1 :]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise PayloadParseError("Maps payload was not valid JSON.") from exc


def strings_in(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings_in(item)


def first_coordinate(value: object) -> tuple[float, float] | None:
    pattern = re.compile(r"(?<![\d.-])(-?\d{1,2}\.\d{4,})[, ]+(-?\d{1,3}\.\d{4,})")
    for text in strings_in(value):
        match = pattern.search(text)
        if match:
            return float(match.group(1)), float(match.group(2))
    return None


def parse_place_card(
    text: str,
) -> tuple[str | None, str | None, float | None, int | None, str | None]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    name = next((line for line in lines if any(character.isalpha() for character in line)), None)
    category = next(
        (line.rstrip("·⋅").strip() for line in lines if line.endswith(("·", "⋅"))), None
    )
    rating_match = re.search(r"\b([1-5]\.?\d?)\s*\(([\d,]+)\)", text)
    rating = float(rating_match.group(1)) if rating_match else None
    review_count = int(rating_match.group(2).replace(",", "")) if rating_match else None
    address_match = re.search(
        r"\d+\s+[\w\s]+(?:St|Ave|Blvd|Rd|Dr|Ln|Way|Pl|Pkwy)\b[^,\n]*(?:,\s*[^,\n]+)*",
        text,
    )
    return (
        name,
        category,
        rating,
        review_count,
        address_match.group(0).strip() if address_match else None,
    )


def parse_routes(text: str) -> list[tuple[str, str, str | None, str | None]]:
    """Parse adjacent duration/distance strings without relying on array offsets."""
    duration = re.compile(r"^(?:(\d+)\s*(?:hr|hour)s?\s*)?(?:(\d+)\s*(?:min|minute)s?)?$", re.I)
    distance = re.compile(
        r"^\d+(?:\.\d+)?\s*(?:ft|feet|mi|mile|miles|km|kilometer|kilometers|m|meter|meters)$",
        re.I,
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    routes: list[tuple[str, str, str | None, str | None]] = []
    for index in range(1, len(lines)):
        if not duration.fullmatch(lines[index - 1]) or not distance.fullmatch(lines[index]):
            continue
        label = (
            lines[index + 1]
            if index + 1 < len(lines) and lines[index + 1].lower().startswith("via ")
            else None
        )
        summary_index = index + 2 if label else index + 1
        summary = (
            lines[summary_index]
            if summary_index < len(lines) and not duration.fullmatch(lines[summary_index])
            else None
        )
        item = (lines[index - 1], lines[index], label, summary)
        if item not in routes:
            routes.append(item)
    return routes
