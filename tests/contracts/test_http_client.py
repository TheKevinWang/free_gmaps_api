from __future__ import annotations

import asyncio

import httpx
import pytest

from free_gmaps_api.http.client import HttpAdapterError, MapsHttpClient, _redact_url
from free_gmaps_api.settings import Settings


async def test_http_client_stops_stream_at_size_limit() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"123456", request=request)

    client = MapsHttpClient(Settings(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(HttpAdapterError, match="5-byte safety limit"):
            await client.get_path(
                "https://www.google.com/search",
                endpoint="bounded",
                params={},
                max_bytes=5,
            )
    finally:
        await client.close()


async def test_http_client_rejects_disallowed_intermediate_redirect() -> None:
    reached_disallowed_host = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal reached_disallowed_host
        if request.url.host == "www.google.com" and request.url.path == "/start":
            return httpx.Response(
                302, headers={"location": "https://example.com/hop"}, request=request
            )
        if request.url.host == "example.com":
            reached_disallowed_host = True
            return httpx.Response(
                302,
                headers={"location": "https://www.google.com/final"},
                request=request,
            )
        return httpx.Response(200, content=b"ok", request=request)

    client = MapsHttpClient(Settings(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(HttpAdapterError, match="non-Google HTTP host"):
            await client.get("https://www.google.com/start", endpoint="redirect")
    finally:
        await client.close()
    assert reached_disallowed_host is False


async def test_http_client_outer_timeout_includes_transport_wait() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, content=b"late", request=request)

    client = MapsHttpClient(Settings(timeout_seconds=0.01), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(HttpAdapterError, match="configured proxy"):
            await client.get("https://www.google.com/maps", endpoint="timeout")
    finally:
        await client.close()


@pytest.mark.parametrize(
    "url,error",
    [
        ("http://www.google.com/maps", "non-HTTPS"),
        ("https://www.google.com:444/maps", "non-default HTTPS port"),
        ("https://user:secret@www.google.com/maps", "containing credentials"),
    ],
)
async def test_http_client_rejects_unsafe_google_urls_before_network(url: str, error: str) -> None:
    reached_network = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal reached_network
        reached_network = True
        return httpx.Response(200, content=b"unsafe", request=request)

    client = MapsHttpClient(Settings(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(HttpAdapterError, match=error):
            await client.get(url, endpoint="unsafe-url")
    finally:
        await client.close()
    assert reached_network is False


def test_redacted_url_never_retains_credentials_or_query() -> None:
    redacted = _redact_url("https://user:secret@www.google.com:443/maps?q=private#fragment")
    assert redacted == "https://www.google.com/maps"
    assert "user" not in redacted
    assert "secret" not in redacted


async def test_post_form_sends_batch_params_and_browser_headers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["rpcids"] == "hspqX"
        assert request.headers["x-same-domain"] == "1"
        assert request.headers["x-maps-diversion-context-bin"] == "CAE="
        assert "Chrome/" in request.headers["user-agent"]
        assert request.content == b"f.req=payload"
        return httpx.Response(200, content=b"ok", request=request)

    client = MapsHttpClient(Settings(), transport=httpx.MockTransport(handler))
    try:
        response = await client.post_form(
            "https://www.google.com/maps/_/MapsWizUi/data/batchexecute",
            endpoint="place-photos",
            params={"rpcids": "hspqX"},
            data={"f.req": "payload"},
        )
    finally:
        await client.close()

    assert response.body == b"ok"
