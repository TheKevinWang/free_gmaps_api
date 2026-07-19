from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

type JsonValue = object


class BootstrapParseError(ValueError):
    """The server HTML did not contain the expected Maps bootstrap JSON."""


@dataclass(frozen=True)
class MapsBootstrap:
    initialization_state: list[JsonValue]
    app_options: list[JsonValue] | dict[str, JsonValue] | None
    final_url: str


def parse_maps_bootstrap(html: str, final_url: str) -> MapsBootstrap:
    state = _parse_assignment(html, "window.APP_INITIALIZATION_STATE")
    if not isinstance(state, list):
        raise BootstrapParseError("APP_INITIALIZATION_STATE must be a JSON array.")
    options = _parse_assignment(html, "window.APP_OPTIONS", optional=True)
    if options is not None and not isinstance(options, (list, dict)):
        raise BootstrapParseError("APP_OPTIONS must be a JSON array or object.")
    return MapsBootstrap(initialization_state=state, app_options=options, final_url=final_url)


def _parse_assignment(html: str, name: str, *, optional: bool = False) -> JsonValue | None:
    marker = f"{name}="
    first = html.find(marker)
    if first < 0:
        if optional:
            return None
        raise BootstrapParseError(f"Missing {name} marker.")
    if html.find(marker, first + len(marker)) >= 0:
        raise BootstrapParseError(f"Duplicate {name} marker.")
    try:
        value, _ = json.JSONDecoder().raw_decode(html[first + len(marker) :].lstrip())
    except json.JSONDecodeError as exc:
        raise BootstrapParseError(f"Invalid {name} JSON.") from exc
    return cast(object, value)
