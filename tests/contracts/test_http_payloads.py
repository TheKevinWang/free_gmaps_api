from __future__ import annotations

import json

from free_gmaps_api.contracts.extracted import CoordinatePair
from free_gmaps_api.contracts.requests import DirectionsRequest
from free_gmaps_api.http.bootstrap import MapsBootstrap
from free_gmaps_api.http.payloads import (
    build_directions_preview_params,
    build_place_photo_batch_request,
    build_place_preview_params,
    build_street_view_metadata_params,
)
from free_gmaps_api.http.street_view import MapsPlaceIdentity


def test_place_builder_changes_query_bearing_payload_only() -> None:
    bootstrap = MapsBootstrap([], None, "https://www.google.com/maps/")
    first = build_place_preview_params("Space Needle", bootstrap, "en-US", "US")
    second = build_place_preview_params("Pike Place", bootstrap, "en-US", "US")
    assert first["hl"] == second["hl"]
    assert first["gl"] == second["gl"]
    assert first["q"] != second["q"]
    assert first["pb"] != second["pb"]


def test_direction_and_street_view_builders_include_named_inputs() -> None:
    bootstrap = MapsBootstrap([], None, "https://www.google.com/maps/")
    directions = build_directions_preview_params(
        DirectionsRequest(origin="Space Needle", destination="Pike Place", travel_mode="walking"),
        bootstrap,
        "en-US",
        None,
    )
    metadata = build_street_view_metadata_params(
        CoordinatePair(lat=39.10176, lng=-84.5121708), bootstrap, "en-US", "US"
    )
    assert "Space Needle" in directions["pb"]
    assert "Pike Place" in directions["pb"]
    assert "!1e1" in directions["pb"]
    assert "39.10176" in metadata["pb"]


def test_place_photo_builder_uses_place_identity_without_session_tokens() -> None:
    identity = MapsPlaceIdentity(
        feature_id="0x8841b15093c01a61:0xcc7b27017af0ac27",
        source_path="/maps/preview/place/520+Vine+St/data=!1s0x8841:0xcc7b",
        canonical_url="https://www.google.com/maps/preview/place/520+Vine+St",
    )

    request = build_place_photo_batch_request(identity, "en-US")
    outer = json.loads(request.data["f.req"])
    service_input = json.loads(outer[0][0][1])

    assert request.params["rpcids"] == "hspqX"
    assert request.params["source-path"] == identity.source_path
    assert request.params["hl"] == "en"
    assert outer[0][0][0] == "/MapsPhotoService.ListEntityPhotos"
    assert service_input[2][0] == identity.feature_id
    assert service_input[5] is None
