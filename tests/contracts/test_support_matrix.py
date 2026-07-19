from __future__ import annotations

import json
from pathlib import Path

import pytest

from free_gmaps_api.contracts.requests import DirectionsRequest
from free_gmaps_api.support.matrix import EndpointName, get_unsupported_fields

_CONTRACTS_DIR = Path(__file__).parent.parent.parent / "contracts" / "google-api-subset" / "v1"

_ENDPOINT_FILES: list[tuple[EndpointName, str]] = [
    ("street-view", "street-view.json"),
    ("geocode", "geocode.json"),
    ("reverse-geocode", "reverse-geocode.json"),
    ("place-search", "place-search.json"),
    ("place-details", "place-details.json"),
    ("directions", "directions.json"),
    ("map-view", "map-view.json"),
    ("distance-matrix", "distance-matrix.json"),
]


@pytest.mark.parametrize("endpoint,filename", _ENDPOINT_FILES)
def test_matrix_file_is_valid_json(endpoint: EndpointName, filename: str) -> None:
    path = _CONTRACTS_DIR / filename
    assert path.exists(), f"Missing contract file: {path}"
    data = json.loads(path.read_text())
    assert "endpoint" in data
    assert "fields" in data
    for field in data["fields"]:
        assert "field" in field
        assert "status" in field
        assert field["status"] in ("supported", "partial", "unsupported", "not_applicable")


def test_directions_unsupported_fields_reported() -> None:
    request = DirectionsRequest(
        origin="A",
        destination="B",
        travel_mode="driving",
        optimize_waypoints=True,
        units="metric",
    )
    unsupported = get_unsupported_fields("directions", request)
    field_names = {u.field for u in unsupported}
    assert "optimize_waypoints" in field_names
    assert "units" in field_names


def test_directions_supported_fields_not_reported() -> None:
    request = DirectionsRequest(origin="A", destination="B", travel_mode="bicycling")
    unsupported = get_unsupported_fields("directions", request)
    field_names = {u.field for u in unsupported}
    assert "origin" not in field_names
    assert "destination" not in field_names
    assert "travel_mode" not in field_names


def test_geocode_unsupported_fields() -> None:
    from free_gmaps_api.contracts.requests import GeocodeRequest

    request = GeocodeRequest(address="Space Needle", bounds="47,122,48,123", region="us")
    unsupported = get_unsupported_fields("geocode", request)
    field_names = {u.field for u in unsupported}
    assert "bounds" in field_names
    assert "region" in field_names
