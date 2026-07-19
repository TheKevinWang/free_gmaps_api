from __future__ import annotations

import json
from dataclasses import dataclass

from free_gmaps_api.contracts.extracted import CoordinatePair
from free_gmaps_api.contracts.requests import DirectionsRequest
from free_gmaps_api.http.bootstrap import MapsBootstrap
from free_gmaps_api.http.street_view import MapsPlaceIdentity


@dataclass(frozen=True)
class PlacePhotoBatchRequest:
    params: dict[str, str]
    data: dict[str, str]


def build_place_preview_params(
    query: str, bootstrap: MapsBootstrap, locale: str, region: str | None
) -> dict[str, str]:
    """Build a minimal named preview payload; opaque bootstrap state stays private."""
    del bootstrap
    return {"hl": locale, "gl": region or "US", "q": query, "pb": f"!1m2!1s{query}"}


def build_directions_preview_params(
    request: DirectionsRequest, bootstrap: MapsBootstrap, locale: str, region: str | None
) -> dict[str, str]:
    del bootstrap
    # This is the smallest cookie-free shape retained from a browser-observed
    # preview request.  The fixed map viewport is context, not a claimed route
    # endpoint; origin and destination remain named request fields.
    return {
        "hl": locale,
        "gl": region or "US",
        "authuser": "0",
        "pb": (
            f"!1m2!1s{request.origin}!6e0"
            f"!1m2!1s{request.destination}!6e0"
            "!3m12!1m3!1d99275.18785207608!2d-122.3321!3d47.6062"
            "!2m3!1f0.0!2f0.0!3f0.0!3m2!1i1024!2i768!4f13.1"
            f"!20m5!1e{_travel_mode_code(request.travel_mode)}!2e3!5e2!6b1!14b1"
        ),
    }


def build_street_view_metadata_params(
    viewpoint: CoordinatePair, bootstrap: MapsBootstrap, locale: str, region: str | None
) -> dict[str, str]:
    del bootstrap
    language = locale.split("-", 1)[0].lower()
    country = (region or "US").lower()
    return {
        "hl": locale,
        "gl": country,
        "authuser": "0",
        "pb": (
            "!1m4!1smaps_sv.tactile!11m2!2m1!1b1"
            f"!2m4!1m2!3d{viewpoint.lat}!4d{viewpoint.lng}!2d50"
            "!3m17!1m2!1m1!1e2"
            f"!2m2!1s{language}!2s{country}"
            "!9m1!1e2!11m8!1m3!1e2!2b1!3e2!1m3!1e3!2b1!3e2"
            "!4m61!1e1!1e2!1e3!1e4!1e5!1e6!1e8!1e12!1e17"
            "!2m1!1e1!4m1!1i48!5m1!1e1!5m1!1e2!6m1!1e1!6m1!1e2"
            "!9m36!1m3!1e2!2b1!3e2!1m3!1e2!2b0!3e3"
            "!1m3!1e3!2b1!3e2!1m3!1e3!2b0!3e3"
            "!1m3!1e8!2b0!3e3!1m3!1e1!2b0!3e3"
            "!1m3!1e4!2b0!3e3!1m3!1e10!2b1!3e2"
            "!1m3!1e10!2b0!3e3!11m2!3m1!4b1"
        ),
    }


def build_place_photo_batch_request(
    identity: MapsPlaceIdentity, locale: str
) -> PlacePhotoBatchRequest:
    """Build the cookie-free request Maps uses for a place's Street View preview."""
    place_record: list[object] = [
        identity.feature_id,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        0,
        None,
        None,
        None,
        None,
        None,
        None,
    ]
    photo_options: list[object] = [
        None,
        [203, 100],
        [None, 20, None, None, 1],
        None,
        None,
        None,
        [
            [
                [1, 0, 3],
                [2, 1, 2],
                [2, 0, 3],
                [8, 0, 3],
                [10, 0, 3],
                [10, 1, 2],
                [10, 0, 4],
                [9, 1, 2],
            ],
            1,
        ],
        None,
        0,
        None,
        None,
        None,
        None,
        None,
        [[[[[[2]]], [195, 195], 20]]],
    ]
    service_input: list[object] = [
        2,
        None,
        place_record,
        None,
        photo_options,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        [None, 1, None, 1],
    ]
    request = [
        [
            [
                "/MapsPhotoService.ListEntityPhotos",
                json.dumps(service_input, separators=(",", ":")),
                None,
                "generic",
            ]
        ]
    ]
    return PlacePhotoBatchRequest(
        params={
            "rpcids": "hspqX",
            "source-path": identity.source_path,
            "hl": locale.split("-", 1)[0].lower(),
            "_reqid": "1",
            "rt": "c",
        },
        data={"f.req": json.dumps(request, separators=(",", ":"))},
    )


def _travel_mode_code(value: str) -> int:
    return {"driving": 0, "walking": 1, "bicycling": 2, "transit": 3}.get(value.lower(), 0)
