from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from free_gmaps_api.contracts.envelope import ApiEnvelope, ProvenanceSource, UnsupportedField
from free_gmaps_api.support.matrix import EndpointName, assert_no_silent_fields

_T = TypeVar("_T", bound=BaseModel)


def assert_envelope_shape(response: ApiEnvelope[Any]) -> None:
    assert response.source == "google_maps_web"
    assert isinstance(response.ok, bool)
    assert isinstance(response.request, dict)
    assert response.confidence is not None
    assert response.confidence.overall in ("high", "medium", "low")
    assert response.artifacts is not None
    assert response.extracted is not None


def assert_field_source(
    response: ApiEnvelope[Any],
    path: str,
    allowed_sources: set[ProvenanceSource],
) -> None:
    parts = path.split(".")
    obj: object = response.extracted
    for part in parts:
        obj = getattr(obj, part, None)
        if obj is None:
            raise AssertionError(f"Path '{path}' not found in extracted.")
    from free_gmaps_api.contracts.envelope import ExtractedField

    if isinstance(obj, ExtractedField):
        assert obj.source in allowed_sources, (
            f"Field '{path}' has source '{obj.source}', expected one of {allowed_sources}."
        )


def assert_unsupported_fields(
    response: ApiEnvelope[Any],
    expected_fields: set[str],
) -> None:
    extracted = response.extracted
    unsupported_list: list[UnsupportedField] = []
    if hasattr(extracted, "unsupported_api_fields"):
        raw = extracted.unsupported_api_fields
        if isinstance(raw, list):
            unsupported_list = [u for u in raw if isinstance(u, UnsupportedField)]
    reported = {u.field for u in unsupported_list}
    missing = expected_fields - reported
    assert not missing, (
        f"Expected these fields in unsupported_api_fields[] but they were absent: {missing}"
    )


def assert_no_unexpected_official_fields(
    endpoint: EndpointName,
    request: BaseModel,
    response: ApiEnvelope[Any],
) -> None:
    extracted = response.extracted
    unsupported_list: list[UnsupportedField] = []
    if hasattr(extracted, "unsupported_api_fields"):
        raw = extracted.unsupported_api_fields
        if isinstance(raw, list):
            unsupported_list = [u for u in raw if isinstance(u, UnsupportedField)]
    assert_no_silent_fields(endpoint, request, unsupported_list)
