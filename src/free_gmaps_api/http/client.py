from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from free_gmaps_api.settings import Settings

_WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)


class HttpAdapterError(RuntimeError):
    """A fail-closed HTTP transport or response validation failure."""


@dataclass(frozen=True)
class HttpExchange:
    endpoint: str
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    body: bytes
    attempts: int


class MapsHttpClient:
    """Small allowlisted client; every network operation uses the configured proxy."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        client_options: dict[str, object] = {
            "transport": transport,
            "follow_redirects": False,
            "timeout": settings.timeout_seconds,
            "headers": {
                "Accept-Language": settings.locale,
                "Referer": "https://www.google.com/maps/",
                "User-Agent": _WEB_USER_AGENT,
            },
        }
        # A supplied transport is a deterministic test double, not a production
        # escape hatch.  Real clients always receive the one configured proxy.
        if transport is None:
            client_options["proxy"] = settings.proxy_url
        self._client = httpx.AsyncClient(**client_options)  # type: ignore[arg-type]

    async def get(self, url: str, *, endpoint: str, referer: str | None = None) -> HttpExchange:
        return await self._request("GET", url, endpoint=endpoint, referer=referer)

    async def get_path(
        self,
        url: str,
        *,
        endpoint: str,
        params: Mapping[str, str],
        referer: str | None = None,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> HttpExchange:
        """GET an allowlisted path without exposing opaque query values in evidence."""

        return await self._request(
            "GET",
            url,
            endpoint=endpoint,
            params=params,
            referer=referer,
            max_bytes=max_bytes,
        )

    async def post_form(
        self,
        url: str,
        *,
        endpoint: str,
        data: Mapping[str, str],
        params: Mapping[str, str] | None = None,
        referer: str | None = None,
    ) -> HttpExchange:
        return await self._request(
            "POST",
            url,
            endpoint=endpoint,
            data=data,
            params=params,
            referer=referer,
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        endpoint: str,
        data: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        referer: str | None = None,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> HttpExchange:
        self._validate_host(url)
        headers: dict[str, str] = {}
        if referer:
            headers["Referer"] = referer
        if method == "POST":
            headers["X-Same-Domain"] = "1"
            headers["x-maps-diversion-context-bin"] = "CAE="
        try:
            async with asyncio.timeout(self._settings.timeout_seconds):
                current_url = url
                current_method = method
                current_data = data
                current_params = params
                for redirect_count in range(6):
                    self._validate_host(current_url)
                    async with self._client.stream(
                        current_method,
                        current_url,
                        data=current_data,
                        params=current_params,
                        headers=headers or None,
                        follow_redirects=False,
                    ) as response:
                        self._validate_host(str(response.url))
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise HttpAdapterError(
                                    f"{endpoint} returned a redirect without Location."
                                )
                            next_url = urljoin(str(response.url), location)
                            # Validate before the next request so even an
                            # intermediate redirect cannot reach another host.
                            self._validate_host(next_url)
                            if redirect_count == 5:
                                raise HttpAdapterError(
                                    f"{endpoint} exceeded the 5-redirect safety limit."
                                )
                            current_url = next_url
                            current_params = None
                            if response.status_code == 303:
                                current_method = "GET"
                                current_data = None
                            continue
                        if response.status_code >= 400:
                            raise HttpAdapterError(
                                f"{endpoint} returned HTTP {response.status_code}."
                            )
                        chunks: list[bytes] = []
                        byte_count = 0
                        async for chunk in response.aiter_bytes():
                            byte_count += len(chunk)
                            if byte_count > max_bytes:
                                raise HttpAdapterError(
                                    f"{endpoint} response exceeded the "
                                    f"{max_bytes}-byte safety limit."
                                )
                            chunks.append(chunk)
                        body = b"".join(chunks)
                        final_url = str(response.url)
                        status_code = response.status_code
                        content_type = response.headers.get("content-type", "")
                        break
        except (httpx.HTTPError, TimeoutError) as exc:
            raise HttpAdapterError(
                f"{endpoint} request failed through configured proxy: {exc}"
            ) from exc
        return HttpExchange(
            endpoint=endpoint,
            requested_url=_redact_url(url),
            final_url=_redact_url(final_url),
            status_code=status_code,
            content_type=content_type.split(";", 1)[0].lower(),
            body=body,
            attempts=1,
        )

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _validate_host(url: str) -> None:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        try:
            port = parsed.port
        except ValueError as exc:
            raise HttpAdapterError("Refusing HTTP URL with an invalid port.") from exc
        if parsed.scheme != "https":
            raise HttpAdapterError("Refusing non-HTTPS Google URL.")
        if parsed.username is not None or parsed.password is not None:
            raise HttpAdapterError("Refusing Google URL containing credentials.")
        if port not in {None, 443}:
            raise HttpAdapterError("Refusing Google URL using a non-default HTTPS port.")
        if hostname == "www.google.com" or hostname.endswith(".google.com"):
            return
        if (
            hostname.endswith(".googleusercontent.com")
            or hostname == "streetviewpixels-pa.googleapis.com"
        ):
            return
        raise HttpAdapterError(f"Refusing non-Google HTTP host {hostname!r}.")


def _redact_url(url: str) -> str:
    parsed = urlsplit(url)
    # Internal pb payloads may be large and opaque. Request summaries retain the
    # host and path, but never persist the value or proxy-like credentials.
    hostname = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = hostname if port in {None, 443} else f"{hostname}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
