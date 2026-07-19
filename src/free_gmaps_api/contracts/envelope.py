from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")
TExtracted = TypeVar("TExtracted", bound=BaseModel)

ProvenanceSource = Literal[
    "url",
    "visible_text",
    "accessibility_tree",
    "screenshot",
    "internal_request_diagnostic",
    "internal_request_promoted",
]


class ExtractedField(BaseModel, Generic[T]):  # noqa: UP046
    model_config = ConfigDict(extra="forbid", strict=True)

    value: T
    source: ProvenanceSource
    confidence: Literal["high", "medium", "low"] | None = None
    notes: list[str] = Field(default_factory=list)


class ArtifactSet(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    screenshot: str | None = None
    street_view_image: str | None = None
    street_view_metadata: str | None = None
    raw_visible_text: str | None = None
    accessibility: str | None = None
    interaction_screenshot: str | None = None
    interaction_visible_text: str | None = None
    interaction_accessibility: str | None = None
    response: str | None = None
    trace: str | None = None


class Confidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    overall: Literal["high", "medium", "low"]
    notes: list[str] = Field(default_factory=list)


class UnsupportedField(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    field: str
    reason: str
    requested_value: object | None = None
    official_api: str | None = None


class ApiEnvelope(BaseModel, Generic[TExtracted]):  # noqa: UP046
    model_config = ConfigDict(extra="forbid", strict=True)

    ok: bool
    source: Literal["google_maps_web"]
    request: dict[str, object]
    maps_url: str | None
    extracted: TExtracted
    artifacts: ArtifactSet
    confidence: Confidence
