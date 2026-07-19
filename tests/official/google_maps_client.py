from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import httpx

JsonObject = dict[str, object]


@dataclass(frozen=True)
class OfficialCoordinate:
    lat: float
    lng: float


@dataclass(frozen=True)
class OfficialStreetViewMetadata:
    status: str
    pano_id: str | None
    location: OfficialCoordinate | None
    copyright: str | None
    date: str | None


@dataclass(frozen=True)
class OfficialStreetViewImage:
    content: bytes
    content_type: str


@dataclass(frozen=True)
class OfficialGeocodeResult:
    formatted_address: str | None
    location: OfficialCoordinate
    place_id: str | None


@dataclass(frozen=True)
class OfficialPlaceResult:
    display_name: str | None
    formatted_address: str | None
    location: OfficialCoordinate | None
    rating: float | None
    user_rating_count: int | None
    google_maps_uri: str | None
    place_id: str | None


@dataclass(frozen=True)
class OfficialDistanceMatrixElement:
    status: str
    distance_text: str | None
    duration_text: str | None


@dataclass(frozen=True)
class OfficialDistanceMatrixResult:
    origin_addresses: list[str]
    destination_addresses: list[str]
    rows: list[list[OfficialDistanceMatrixElement]]


@dataclass(frozen=True)
class OfficialRoute:
    duration_seconds: int
    static_duration_seconds: int | None
    distance_meters: int
    route_labels: list[str]


@dataclass(frozen=True)
class OfficialRoutesResult:
    routes: list[OfficialRoute]


class OfficialGoogleMapsClient:
    def __init__(self, api_key: str, client: httpx.Client) -> None:
        self._api_key = api_key
        self._client = client

    def geocode(self, address: str) -> OfficialGeocodeResult:
        response = self._client.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": self._api_key},
        )
        payload = _json_object(response)
        _assert_legacy_status_ok(payload, "Geocoding API")
        results = _object_list(payload, "results")
        if not results:
            raise AssertionError("Geocoding API returned OK with no results.")

        first = results[0]
        geometry = _required_object(first, "geometry")
        location = _required_object(geometry, "location")
        return OfficialGeocodeResult(
            formatted_address=_optional_string(first.get("formatted_address")),
            location=OfficialCoordinate(
                lat=_required_float(location, "lat"),
                lng=_required_float(location, "lng"),
            ),
            place_id=_optional_string(first.get("place_id")),
        )

    def text_search(self, query: str) -> OfficialPlaceResult:
        response = self._client.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "X-Goog-Api-Key": self._api_key,
                "X-Goog-FieldMask": (
                    "places.id,places.displayName,places.formattedAddress,"
                    "places.location,places.rating,places.userRatingCount,"
                    "places.googleMapsUri"
                ),
            },
            json={"textQuery": query, "languageCode": "en"},
        )
        payload = _json_object(response)
        places = _object_list(payload, "places")
        if not places:
            raise AssertionError("Places Text Search API returned no places.")

        first = places[0]
        display_name_obj = _optional_object(first, "displayName")
        location_obj = _optional_object(first, "location")
        location: OfficialCoordinate | None = None
        if location_obj is not None:
            location = OfficialCoordinate(
                lat=_required_float(location_obj, "latitude"),
                lng=_required_float(location_obj, "longitude"),
            )

        return OfficialPlaceResult(
            display_name=_optional_string(display_name_obj.get("text"))
            if display_name_obj is not None
            else None,
            formatted_address=_optional_string(first.get("formattedAddress")),
            location=location,
            rating=_optional_float(first.get("rating")),
            user_rating_count=_optional_int(first.get("userRatingCount")),
            google_maps_uri=_optional_string(first.get("googleMapsUri")),
            place_id=_optional_string(first.get("id")),
        )

    def street_view_metadata(
        self,
        location: str | None = None,
        pano: str | None = None,
    ) -> OfficialStreetViewMetadata:
        params: dict[str, str] = {"key": self._api_key}
        if location is not None:
            params["location"] = location
        if pano is not None:
            params["pano"] = pano
        response = self._client.get(
            "https://maps.googleapis.com/maps/api/streetview/metadata",
            params=params,
        )
        payload = _json_object(response)
        status = _optional_string(payload.get("status")) or "UNKNOWN"
        location_obj = _optional_object(payload, "location")
        loc: OfficialCoordinate | None = None
        if location_obj is not None:
            loc = OfficialCoordinate(
                lat=_required_float(location_obj, "lat"),
                lng=_required_float(location_obj, "lng"),
            )
        return OfficialStreetViewMetadata(
            status=status,
            pano_id=_optional_string(payload.get("pano_id")),
            location=loc,
            copyright=_optional_string(payload.get("copyright")),
            date=_optional_string(payload.get("date")),
        )

    def street_view_image(
        self,
        *,
        pano: str,
        size: str,
        heading: float,
        pitch: float,
        fov: float,
    ) -> OfficialStreetViewImage:
        response = self._client.get(
            "https://maps.googleapis.com/maps/api/streetview",
            params={
                "pano": pano,
                "size": size,
                "heading": str(heading),
                "pitch": str(pitch),
                "fov": str(fov),
                "return_error_code": "true",
                "key": self._api_key,
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AssertionError(
                f"Official Street View image HTTP {response.status_code}."
            ) from exc
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type not in {"image/jpeg", "image/png"}:
            raise AssertionError(
                f"Official Street View image returned content type {content_type!r}."
            )
        return OfficialStreetViewImage(content=response.content, content_type=content_type)

    def distance_matrix(
        self,
        origins: list[str],
        destinations: list[str],
        travel_mode: str,
    ) -> OfficialDistanceMatrixResult:
        response = self._client.get(
            "https://maps.googleapis.com/maps/api/distancematrix/json",
            params={
                "origins": "|".join(origins),
                "destinations": "|".join(destinations),
                "mode": travel_mode,
                "key": self._api_key,
            },
        )
        payload = _json_object(response)
        _assert_legacy_status_ok(payload, "Distance Matrix API")

        rows: list[list[OfficialDistanceMatrixElement]] = []
        for row in _object_list(payload, "rows"):
            elements: list[OfficialDistanceMatrixElement] = []
            for element in _object_list(row, "elements"):
                distance = _optional_object(element, "distance")
                duration = _optional_object(element, "duration")
                elements.append(
                    OfficialDistanceMatrixElement(
                        status=_required_string(element, "status"),
                        distance_text=_optional_string(distance.get("text"))
                        if distance is not None
                        else None,
                        duration_text=_optional_string(duration.get("text"))
                        if duration is not None
                        else None,
                    )
                )
            rows.append(elements)

        return OfficialDistanceMatrixResult(
            origin_addresses=_string_list(payload, "origin_addresses"),
            destination_addresses=_string_list(payload, "destination_addresses"),
            rows=rows,
        )

    def compute_routes(
        self,
        *,
        origin: str,
        destination: str,
        alternatives: bool,
    ) -> OfficialRoutesResult:
        response = self._client.post(
            "https://routes.googleapis.com/directions/v2:computeRoutes",
            headers={
                "X-Goog-Api-Key": self._api_key,
                "X-Goog-FieldMask": (
                    "routes.duration,routes.staticDuration,routes.distanceMeters,routes.routeLabels"
                ),
            },
            json={
                "origin": {"address": origin},
                "destination": {"address": destination},
                "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE",
                "computeAlternativeRoutes": alternatives,
                "languageCode": "en-US",
                "units": "IMPERIAL",
            },
        )
        payload = _json_object(response)
        routes: list[OfficialRoute] = []
        for route in _object_list(payload, "routes"):
            duration = _required_string(route, "duration")
            static_duration = _optional_string(route.get("staticDuration"))
            routes.append(
                OfficialRoute(
                    duration_seconds=_duration_seconds(duration),
                    static_duration_seconds=(
                        _duration_seconds(static_duration) if static_duration is not None else None
                    ),
                    distance_meters=round(_required_float(route, "distanceMeters")),
                    route_labels=_string_list(route, "routeLabels"),
                )
            )
        if not routes:
            raise AssertionError("Routes API returned no routes.")
        return OfficialRoutesResult(routes=routes)


@contextmanager
def official_client(api_key: str) -> Iterator[OfficialGoogleMapsClient]:
    with httpx.Client(timeout=30.0) as client:
        yield OfficialGoogleMapsClient(api_key=api_key, client=client)


def _json_object(response: httpx.Response) -> JsonObject:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AssertionError(f"Official API HTTP error: {exc}") from exc

    payload: object = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("Official API response was not a JSON object.")
    return {str(key): value for key, value in payload.items()}


def _assert_legacy_status_ok(payload: JsonObject, api_name: str) -> None:
    status = _optional_string(payload.get("status"))
    if status != "OK":
        error_message = _optional_string(payload.get("error_message"))
        detail = f": {error_message}" if error_message else ""
        raise AssertionError(f"{api_name} returned status {status!r}{detail}.")


def _object_list(parent: JsonObject, key: str) -> list[JsonObject]:
    value = parent.get(key)
    if not isinstance(value, list):
        return []
    result: list[JsonObject] = []
    for item in value:
        if isinstance(item, dict):
            result.append({str(item_key): item_value for item_key, item_value in item.items()})
    return result


def _string_list(parent: JsonObject, key: str) -> list[str]:
    value = parent.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _required_object(parent: JsonObject, key: str) -> JsonObject:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise AssertionError(f"Expected official field {key!r} to be an object.")
    return {str(item_key): item_value for item_key, item_value in value.items()}


def _optional_object(parent: JsonObject, key: str) -> JsonObject | None:
    value = parent.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AssertionError(f"Expected official field {key!r} to be an object when present.")
    return {str(item_key): item_value for item_key, item_value in value.items()}


def _required_string(parent: JsonObject, key: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str):
        raise AssertionError(f"Expected official field {key!r} to be a string.")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _required_float(parent: JsonObject, key: str) -> float:
    value = parent.get(key)
    if isinstance(value, int | float):
        return float(value)
    raise AssertionError(f"Expected official field {key!r} to be numeric.")


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _duration_seconds(value: str) -> int:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)s", value)
    if match is None:
        raise AssertionError(f"Expected protobuf duration string, got {value!r}.")
    return round(float(match.group(1)))
