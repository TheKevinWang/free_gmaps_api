from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from free_gmaps_api.contracts.extracted import CoordinatePair

_PHOTO_SERVICE = "/MapsPhotoService.ListEntityPhotos"
_FEATURE_ID = re.compile(r"0x[0-9a-f]+:0x[0-9a-f]+", re.IGNORECASE)
_THUMBNAIL_HOST = "streetviewpixels-pa.googleapis.com"
_THUMBNAIL_PATH = "/v1/thumbnail"


class PlaceStreetViewParseError(ValueError):
    """A Maps place-photo response was malformed or had no trustworthy panorama."""


@dataclass(frozen=True)
class MapsPlaceIdentity:
    feature_id: str
    source_path: str
    canonical_url: str


@dataclass(frozen=True)
class PlaceStreetViewPanorama:
    pano_id: str
    coordinates: CoordinatePair
    renderer_url: str
    heading: float | None
    capture_date: str | None


def place_identity_from_url(url: str) -> MapsPlaceIdentity | None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "www.google.com":
        return None
    if not parsed.path.startswith("/maps/"):
        return None
    match = _FEATURE_ID.search(unquote(parsed.path))
    if match is None:
        return None
    return MapsPlaceIdentity(
        feature_id=match.group(0),
        source_path=parsed.path,
        canonical_url=urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")),
    )


def exact_panorama_renderer_url(pano_id: str) -> str:
    value = pano_id.strip()
    if not value or len(value) > 256 or any(character in value for character in "\r\n"):
        raise ValueError("Street View panorama ID is empty or invalid.")
    return urlunsplit(
        (
            "https",
            _THUMBNAIL_HOST,
            _THUMBNAIL_PATH,
            urlencode({"panoid": value, "cb_client": "maps_sv.tactile.gps"}),
            "",
        )
    )


def parse_place_street_view_response(body: bytes) -> PlaceStreetViewPanorama:
    service_payloads: list[object] = []
    for chunk in _batch_chunks(body):
        for row in _lists(chunk):
            if (
                len(row) >= 3
                and row[0] == "wrb.fr"
                and row[1] == _PHOTO_SERVICE
                and isinstance(row[2], str)
            ):
                try:
                    service_payloads.append(json.loads(row[2]))
                except json.JSONDecodeError as exc:
                    raise PlaceStreetViewParseError(
                        "Maps place-photo service returned malformed nested JSON."
                    ) from exc
    if not service_payloads:
        raise PlaceStreetViewParseError(
            "Maps place-photo batch response did not contain the expected service result."
        )

    for payload in service_payloads:
        panorama = _panorama_in(payload)
        if panorama is not None:
            return panorama
    raise PlaceStreetViewParseError(
        "Maps place record did not expose a valid Street View panorama."
    )


def _batch_chunks(body: bytes) -> Iterator[object]:
    prefix = b")]}'"
    payload = body.lstrip(b"\xef\xbb\xbf")
    if not payload.startswith(prefix):
        raise PlaceStreetViewParseError("Maps batch response was missing its anti-XSSI prefix.")
    newline = payload.find(b"\n", len(prefix))
    if newline < 0:
        raise PlaceStreetViewParseError("Maps batch response had no framed payload.")
    try:
        text = payload[newline + 1 :].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlaceStreetViewParseError("Maps batch response was not UTF-8.") from exc
    decoder = json.JSONDecoder()
    position = 0
    while position < len(text):
        while position < len(text) and text[position] in " \t\r\n":
            position += 1
        if position >= len(text):
            return
        length_start = position
        while position < len(text) and text[position].isdigit():
            position += 1
        if position == length_start or position >= len(text):
            raise PlaceStreetViewParseError("Maps batch response had invalid length framing.")
        try:
            length = int(text[length_start:position])
        except ValueError as exc:
            raise PlaceStreetViewParseError(
                "Maps batch response had invalid length framing."
            ) from exc
        if length <= 0 or length > 2 * 1024 * 1024:
            raise PlaceStreetViewParseError("Maps batch frame declared an unsafe length.")
        if text[position : position + 2] == "\r\n":
            position += 2
        elif text[position : position + 1] == "\n":
            position += 1
        else:
            raise PlaceStreetViewParseError("Maps batch length was not followed by a newline.")
        try:
            chunk, end = decoder.raw_decode(text, position)
            yield chunk
        except json.JSONDecodeError as exc:
            raise PlaceStreetViewParseError("Maps batch frame was not valid JSON.") from exc
        position = end


def _panorama_in(payload: object) -> PlaceStreetViewPanorama | None:
    for node in _lists(payload):
        if not node or not isinstance(node[0], str):
            continue
        pano_id = node[0]
        renderer_url = _matching_renderer_url(node, pano_id)
        if renderer_url is None:
            continue
        coordinates = _photo_coordinates(node)
        if coordinates is None:
            continue
        query = dict(parse_qsl(urlsplit(renderer_url).query, keep_blank_values=True))
        heading = _optional_float(query.get("yaw"))
        return PlaceStreetViewPanorama(
            pano_id=pano_id,
            coordinates=coordinates,
            renderer_url=renderer_url,
            heading=heading,
            capture_date=_capture_date(node),
        )
    return None


def _matching_renderer_url(value: object, pano_id: str) -> str | None:
    for item in _strings(value):
        parsed = urlsplit(item)
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").lower() != _THUMBNAIL_HOST
            or parsed.path != _THUMBNAIL_PATH
        ):
            continue
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if query.get("panoid") == pano_id:
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    return None


def _photo_coordinates(value: object) -> CoordinatePair | None:
    for item in _lists(value):
        if len(item) < 3 or item[0] != 3:
            continue
        lng = _number(item[1])
        lat = _number(item[2])
        if lat is None or lng is None:
            continue
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return CoordinatePair(lat=lat, lng=lng)
    return None


def _capture_date(value: object) -> str | None:
    for item in _lists(value):
        if len(item) < 2:
            continue
        year = item[0]
        month = item[1]
        if (
            isinstance(year, int)
            and not isinstance(year, bool)
            and isinstance(month, int)
            and not isinstance(month, bool)
            and 2000 <= year <= 2100
            and 1 <= month <= 12
        ):
            return f"{year:04d}-{month:02d}"
    return None


def _lists(value: object) -> Iterator[list[object]]:
    if isinstance(value, list):
        yield value
        for item in value:
            yield from _lists(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _lists(item)


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _optional_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
