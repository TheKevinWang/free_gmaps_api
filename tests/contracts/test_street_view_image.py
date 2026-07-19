from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from free_gmaps_api.browser.street_view_image import (
    build_renderer_url,
    download_clean_street_view_image,
    find_renderer_url,
    image_dimensions,
    parse_size,
    renderer_url_from_metadata,
)

_IMAGE_KEY = "example-panorama-key"
_RENDERER = (
    f"https://lh3.googleusercontent.com/gpms-cs-s/{_IMAGE_KEY}=w900-h600-k-no-pi0-ya243-ro0-fo100"
)


def _jpeg(width: int, height: int) -> bytes:
    return (
        b"\xff\xd8\xff\xc0\x00\x08\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x00\xff\xd9"
    )


def test_find_and_rewrite_googleusercontent_renderer() -> None:
    maps_url = (
        "https://www.google.com/maps/@39.1,-84.5,3a,80y,45h,90t/"
        f"data=!3m7!6s{_RENDERER.replace(':', '%3A').replace('/', '%2F').replace('=', '%3D')}"
        "!7i4000!8i2000"
    )
    observed = find_renderer_url([maps_url])
    assert observed == _RENDERER
    rewritten = build_renderer_url(observed, width=640, height=360, fov=80.0)
    assert rewritten.endswith("=w640-h360-k-no-pi0-ya243-ro0-fo80")


def test_streetview_thumbnail_requires_nonempty_panoid() -> None:
    empty = (
        "https://streetviewpixels-pa.googleapis.com/v1/thumbnail"
        "?cb_client=maps_sv.tactile&w=900&h=600&panoid&yaw=210"
    )
    valid = empty.replace("panoid&", "panoid=abc123&")
    assert find_renderer_url([empty]) is None
    assert find_renderer_url([valid]) == valid
    rewritten = build_renderer_url(
        valid,
        width=640,
        height=360,
        fov=80.0,
        heading=45.0,
        pitch=-5.0,
    )
    assert "w=640" in rewritten
    assert "h=360" in rewritten
    assert "panoid=abc123" in rewritten
    assert "cb_client=maps_sv.tactile.gps" in rewritten
    assert "yaw=45" in rewritten
    assert "pitch=-5" in rewritten
    assert "thumbfov=80" in rewritten


def test_renderer_rejects_non_google_host() -> None:
    assert find_renderer_url(["https://example.com/image.jpg"]) is None


def test_build_renderer_from_photometa_orientation() -> None:
    metadata = (
        ")]}'\n[[[[null,null,39.10176000581,-84.51217081665],null,[162,90,0]]],"
        f'[["https://lh3.googleusercontent.com/gpms-cs-s/{_IMAGE_KEY}=w0-h0-k-no"]]]'
    )
    renderer = renderer_url_from_metadata(
        metadata,
        heading=45.0,
        pitch=0.0,
        fov=80.0,
    )
    assert renderer is not None
    assert renderer.endswith("=w0-h0-k-no-pi0-ya243-ro0-fo80")
    default_sized = build_renderer_url(renderer, width=None, height=None, fov=80.0)
    assert default_sized.endswith("=w640-h360-k-no-pi0-ya243-ro0-fo80")


def test_parse_size_and_image_dimensions() -> None:
    assert parse_size("640x360") == (640, 360)
    assert image_dimensions(_jpeg(640, 360)) == (640, 360)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (640).to_bytes(4, "big") + (360).to_bytes(4, "big")
    assert image_dimensions(png) == (640, 360)


async def test_download_clean_renderer_validates_and_writes_image(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["referer"] == "https://www.google.com/"
        assert not request.url.query
        assert str(request.url).endswith("=w640-h360-k-no-pi0-ya243-ro0-fo80")
        return httpx.Response(
            200,
            headers={"content-type": "image/jpeg"},
            content=_jpeg(640, 360),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Referer": "https://www.google.com/"},
    ) as client:
        result = await download_clean_street_view_image(
            [_RENDERER],
            tmp_path,
            width=640,
            height=360,
            fov=80.0,
            timeout_seconds=1.0,
            client=client,
        )

    assert result is not None
    assert (result.width, result.height) == (640, 360)
    assert result.content_type == "image/jpeg"
    assert Path(result.path).read_bytes() == _jpeg(640, 360)


async def test_download_clean_renderer_validates_each_redirect(tmp_path: Path) -> None:
    redirected = "https://streetviewpixels-pa.googleapis.com/v1/thumbnail?panoid=abc123&w=640&h=360"
    requested_hosts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(str(request.url.host))
        if request.url.host == "lh3.googleusercontent.com":
            return httpx.Response(302, headers={"location": redirected})
        return httpx.Response(
            200,
            headers={"content-type": "image/jpeg"},
            content=_jpeg(640, 360),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        result = await download_clean_street_view_image(
            [_RENDERER],
            tmp_path,
            width=640,
            height=360,
            fov=80.0,
            timeout_seconds=1.0,
            client=client,
        )

    assert result is not None
    assert requested_hosts == [
        "lh3.googleusercontent.com",
        "streetviewpixels-pa.googleapis.com",
    ]
    assert result.renderer_url.startswith(redirected)


async def test_download_clean_renderer_rejects_cross_host_redirect(tmp_path: Path) -> None:
    requested_hosts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(str(request.url.host))
        return httpx.Response(302, headers={"location": "https://example.com/image.jpg"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="allowlisted"):
            await download_clean_street_view_image(
                [_RENDERER],
                tmp_path,
                width=640,
                height=360,
                fov=80.0,
                timeout_seconds=1.0,
                client=client,
            )

    assert requested_hosts == ["lh3.googleusercontent.com"]
    assert list(tmp_path.iterdir()) == []


async def test_download_clean_renderer_rejects_oversized_body(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "image/jpeg"},
            content=_jpeg(640, 360) + b"oversized",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="exceeded"):
            await download_clean_street_view_image(
                [_RENDERER],
                tmp_path,
                width=640,
                height=360,
                fov=80.0,
                timeout_seconds=1.0,
                client=client,
                max_bytes=8,
            )

    assert list(tmp_path.iterdir()) == []
