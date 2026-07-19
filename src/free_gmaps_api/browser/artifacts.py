from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from free_gmaps_api.contracts.envelope import ArtifactSet


def make_artifact_dir(base: Path, request_id: str | None = None) -> Path:
    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    rid = request_id or uuid.uuid4().hex
    artifact_dir = base / today / rid
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def artifact_set_from_navigation(navigation: dict[str, object]) -> ArtifactSet:
    return ArtifactSet(
        screenshot=_optional_path(navigation.get("screenshot")),
        street_view_image=_optional_path(navigation.get("street_view_image")),
        street_view_metadata=_optional_path(navigation.get("street_view_metadata")),
        raw_visible_text=_optional_path(navigation.get("visible_text_path")),
        accessibility=_optional_path(navigation.get("accessibility_path")),
        interaction_screenshot=_optional_path(navigation.get("interaction_screenshot")),
        interaction_visible_text=_optional_path(navigation.get("interaction_visible_text_path")),
        interaction_accessibility=_optional_path(navigation.get("interaction_accessibility_path")),
        response=_optional_path(navigation.get("response_path")),
        trace=_optional_path(navigation.get("trace_path")),
    )


def _optional_path(value: object) -> str | None:
    if value is None:
        return None
    path = str(value)
    return path if path else None
