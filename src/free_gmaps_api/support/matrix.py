from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from free_gmaps_api.contracts.envelope import UnsupportedField

SupportStatus = Literal["supported", "partial", "unsupported", "not_applicable"]

EndpointName = Literal[
    "street-view",
    "geocode",
    "reverse-geocode",
    "place-search",
    "place-details",
    "directions",
    "map-view",
    "distance-matrix",
    "elevation",
    "time-zone",
]

_PACKAGED_CONTRACTS_DIR = Path(__file__).parent.parent / "contracts" / "google-api-subset" / "v1"
_REPOSITORY_CONTRACTS_DIR = (
    Path(__file__).parent.parent.parent.parent / "contracts" / "google-api-subset" / "v1"
)
_CONTRACTS_DIR = (
    _PACKAGED_CONTRACTS_DIR if _PACKAGED_CONTRACTS_DIR.is_dir() else _REPOSITORY_CONTRACTS_DIR
)


class SupportMatrixEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    field: str
    status: SupportStatus
    notes: str | None = None
    official_api: str | None = None


class EndpointSupportMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    endpoint: str
    fields: list[SupportMatrixEntry] = Field(default_factory=list)


_cache: dict[str, EndpointSupportMatrix] = {}


def _load_matrix(endpoint: EndpointName) -> EndpointSupportMatrix:
    if endpoint in _cache:
        return _cache[endpoint]
    path = _CONTRACTS_DIR / f"{endpoint}.json"
    if not path.exists():
        matrix = EndpointSupportMatrix(endpoint=endpoint, fields=[])
        _cache[endpoint] = matrix
        return matrix
    with path.open() as f:
        data = json.load(f)
    matrix = EndpointSupportMatrix.model_validate(data)
    _cache[endpoint] = matrix
    return matrix


def get_unsupported_fields(endpoint: EndpointName, request: BaseModel) -> list[UnsupportedField]:
    matrix = _load_matrix(endpoint)
    status_map = {e.field: e for e in matrix.fields}
    result: list[UnsupportedField] = []
    for field_name, value in request.model_dump(exclude_none=False).items():
        if value is None or value == [] or value is False:
            continue
        entry = status_map.get(field_name)
        if entry is None:
            continue
        if entry.status in ("unsupported", "not_applicable"):
            result.append(
                UnsupportedField(
                    field=field_name,
                    reason=entry.notes
                    or f"Field '{field_name}' is {entry.status} in the browser implementation.",
                    requested_value=value,
                    official_api=entry.official_api,
                )
            )
    return result


def assert_no_silent_fields(
    endpoint: EndpointName,
    request: BaseModel,
    response_unsupported: list[UnsupportedField],
) -> None:
    matrix = _load_matrix(endpoint)
    status_map = {e.field: e for e in matrix.fields}
    reported_fields = {u.field for u in response_unsupported}
    for field_name, value in request.model_dump(exclude_none=False).items():
        if value is None or value == [] or value is False:
            continue
        entry = status_map.get(field_name)
        if entry is None:
            continue
        if entry.status in ("unsupported", "not_applicable") and field_name not in reported_fields:
            raise AssertionError(
                f"Field '{field_name}' is {entry.status} for endpoint '{endpoint}' "
                f"but was not reported in unsupported_api_fields[]."
            )
