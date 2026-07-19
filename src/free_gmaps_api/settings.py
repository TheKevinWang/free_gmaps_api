from __future__ import annotations

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MapsBackendName = Literal["http", "zendriver"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GMAPS_", extra="ignore")

    headless: bool = True
    locale: str = "en-US"
    artifact_dir: str = ".free-gmaps-api/artifacts"
    timeout_seconds: float = 30.0
    navigation_settle_seconds: float = 5.0
    interaction_settle_seconds: float = 2.0
    trace: bool = False
    host: str = "127.0.0.1"
    port: int = 8787

    @field_validator("proxy_url")
    @classmethod
    def validate_proxy_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https", "socks5", "socks5h"}:
            raise ValueError("GMAPS_PROXY_URL must use http, https, socks5, or socks5h.")
        if not parsed.hostname or parsed.port is None:
            raise ValueError("GMAPS_PROXY_URL must include a host and port.")
        return value

    backend: MapsBackendName = "http"
    proxy_url: str = "socks5://localhost:9050"
