from __future__ import annotations

from urllib.parse import urlsplit


def validate_google_maps_url(value: str) -> str:
    """Accept only credential-free HTTPS URLs on the canonical Maps origin."""

    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Maps URL contains an invalid port.") from exc
    if parsed.scheme != "https":
        raise ValueError("Maps URL must use HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Maps URL must not contain credentials.")
    if parsed.hostname != "www.google.com" or port not in {None, 443}:
        raise ValueError("Maps URL must use the canonical www.google.com origin.")
    if not parsed.path.startswith("/maps/"):
        raise ValueError("Maps URL must point beneath /maps/.")
    return value
