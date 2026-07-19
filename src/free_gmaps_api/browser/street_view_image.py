from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx

_GOOGLEUSERCONTENT_HOST = re.compile(r"^lh\d+\.googleusercontent\.com$")
_STREET_VIEW_PIXEL_HOST = "streetviewpixels-pa.googleapis.com"
_EMBEDDED_RENDERER = re.compile(r"!6s(https://[^!]+)")
_PATH_DIMENSIONS = re.compile(r"=w(?P<width>\d+)-h(?P<height>\d+)(?P<suffix>.*)$")
_PATH_FOV = re.compile(r"-fo-?\d+(?:\.\d+)?")
_SIZE = re.compile(r"^(?P<width>\d+)x(?P<height>\d+)$")
_METADATA_IMAGE_BASE = re.compile(r'"(https://lh\d+\.googleusercontent\.com/[^"\\]+=w0-h0-k-no)"')
_METADATA_ORIENTATION = re.compile(
    r"\[\[null,null,-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?\],null,"
    r"\[(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)\]\]"
)
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_RENDERER_BYTES = 20 * 1024 * 1024
MAX_RENDERER_REDIRECTS = 5


@dataclass(frozen=True)
class CleanStreetViewImage:
    path: str
    width: int
    height: int
    content_type: str
    renderer_url: str


def parse_size(value: str) -> tuple[int, int]:
    match = _SIZE.fullmatch(value.strip())
    if match is None:
        raise ValueError("Street View size must use WIDTHxHEIGHT, for example 640x360.")
    width = int(match.group("width"))
    height = int(match.group("height"))
    if width <= 0 or height <= 0:
        raise ValueError("Street View size dimensions must be positive.")
    return width, height


def find_renderer_url(urls: list[str]) -> str | None:
    for value in urls:
        decoded = unquote(value)
        direct = _validated_renderer_url(decoded)
        if direct is not None:
            return direct
        for match in _EMBEDDED_RENDERER.finditer(decoded):
            embedded = _validated_renderer_url(match.group(1))
            if embedded is not None:
                return embedded
    return None


def build_renderer_url(
    renderer_url: str,
    width: int | None,
    height: int | None,
    fov: float | None,
    *,
    heading: float | None = None,
    pitch: float | None = None,
) -> str:
    validated = _validated_renderer_url(renderer_url)
    if validated is None:
        raise ValueError("Street View renderer URL is missing, unsafe, or incomplete.")

    parsed = urlsplit(validated)
    if _GOOGLEUSERCONTENT_HOST.fullmatch(parsed.hostname or ""):
        path = parsed.path
        match = _PATH_DIMENSIONS.search(path)
        if match is None:
            raise ValueError("Googleusercontent renderer URL has no image dimensions.")
        observed_width = int(match.group("width"))
        observed_height = int(match.group("height"))
        selected_width = width if width is not None else observed_width or 640
        selected_height = height if height is not None else observed_height or 360
        suffix = match.group("suffix")
        if fov is not None:
            fov_token = _format_number(fov)
            if _PATH_FOV.search(suffix):
                suffix = _PATH_FOV.sub(f"-fo{fov_token}", suffix)
            else:
                suffix += f"-fo{fov_token}"
        path = path[: match.start()] + f"=w{selected_width}-h{selected_height}{suffix}"
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    # Place-photo responses sometimes label the preview as unknown_client.gws.gps,
    # which limits a requested 640x360 image to roughly 497x280. The Maps Street
    # View viewer uses this stable client name and returns the requested geometry.
    query["cb_client"] = "maps_sv.tactile.gps"
    if width is not None:
        query["w"] = str(width)
    if height is not None:
        query["h"] = str(height)
    if heading is not None:
        query["yaw"] = _format_number(heading)
    if pitch is not None:
        query["pitch"] = _format_number(pitch)
    if fov is not None:
        query["thumbfov"] = _format_number(fov)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def renderer_url_from_metadata(
    metadata_body: str,
    *,
    heading: float | None,
    pitch: float | None,
    fov: float | None,
) -> str | None:
    normalized = metadata_body.replace(r"\u003d", "=").replace(r"\/", "/")
    image_match = _METADATA_IMAGE_BASE.search(normalized)
    orientation_match = _METADATA_ORIENTATION.search(normalized)
    if image_match is None or orientation_match is None:
        return None

    image_base = image_match.group(1)
    panorama_heading = float(orientation_match.group(1))
    roll = float(orientation_match.group(3))
    requested_heading = panorama_heading if heading is None else heading
    requested_pitch = 0.0 if pitch is None else pitch
    requested_fov = 90.0 if fov is None else fov
    renderer_yaw = (requested_heading - panorama_heading) % 360.0
    renderer_url = (
        f"{image_base}-pi{_format_number(requested_pitch)}"
        f"-ya{_format_number(renderer_yaw)}"
        f"-ro{_format_number(roll)}"
        f"-fo{_format_number(requested_fov)}"
    )
    return _validated_renderer_url(renderer_url)


async def download_clean_street_view_image(
    urls: list[str],
    artifact_dir: Path,
    width: int | None,
    height: int | None,
    fov: float | None,
    *,
    timeout_seconds: float,
    client: httpx.AsyncClient | None = None,
    max_bytes: int = MAX_RENDERER_BYTES,
    max_redirects: int = MAX_RENDERER_REDIRECTS,
) -> CleanStreetViewImage | None:
    observed_url = find_renderer_url(urls)
    if observed_url is None:
        return None
    renderer_url = build_renderer_url(observed_url, width, height, fov)

    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        follow_redirects=False,
        timeout=timeout_seconds,
        headers={"Referer": "https://www.google.com/"},
    )
    try:
        data, content_type, final_url = await _download_renderer_bytes(
            active_client,
            renderer_url,
            max_bytes=max_bytes,
            max_redirects=max_redirects,
        )
        image_width, image_height = image_dimensions(data)
        extension = ".jpg" if content_type == "image/jpeg" else ".png"
        destination = artifact_dir / f"street-view{extension}"
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(destination)
        return CleanStreetViewImage(
            path=str(destination),
            width=image_width,
            height=image_height,
            content_type=content_type,
            renderer_url=final_url,
        )
    finally:
        if owns_client:
            await active_client.aclose()


def image_dimensions(data: bytes) -> tuple[int, int]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) < 24:
            raise ValueError("PNG image response is truncated.")
        width, height = struct.unpack(">II", data[16:24])
        if width <= 0 or height <= 0:
            raise ValueError("PNG image response has invalid dimensions.")
        return width, height
    if data.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(data)
    raise ValueError("Renderer response is not a JPEG or PNG image.")


def image_dimensions_from_file(path: str) -> tuple[int, int] | None:
    try:
        return image_dimensions(Path(path).read_bytes())
    except (OSError, ValueError):
        return None


def _validated_renderer_url(value: str) -> str | None:
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if parsed.username is not None or parsed.password is not None or port not in {None, 443}:
        return None
    if not (_GOOGLEUSERCONTENT_HOST.fullmatch(hostname) or hostname == _STREET_VIEW_PIXEL_HOST):
        return None
    if hostname == _STREET_VIEW_PIXEL_HOST:
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if parsed.path != "/v1/thumbnail" or not query.get("panoid"):
            return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


async def _download_renderer_bytes(
    client: httpx.AsyncClient,
    renderer_url: str,
    *,
    max_bytes: int,
    max_redirects: int,
) -> tuple[bytes, str, str]:
    if max_bytes <= 0:
        raise ValueError("Renderer response byte limit must be positive.")
    if max_redirects < 0:
        raise ValueError("Renderer redirect limit may not be negative.")

    current_url = renderer_url
    for redirect_count in range(max_redirects + 1):
        validated_url = _validated_renderer_url(current_url)
        if validated_url is None:
            raise ValueError("Renderer redirect target is not an allowlisted Google image URL.")

        async with client.stream("GET", validated_url, follow_redirects=False) as response:
            if response.status_code in _REDIRECT_STATUSES:
                if redirect_count >= max_redirects:
                    raise ValueError(f"Renderer exceeded {max_redirects} redirects.")
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Renderer redirect did not provide a Location header.")
                current_url = urljoin(str(response.url), location)
                if _validated_renderer_url(current_url) is None:
                    raise ValueError(
                        "Renderer redirect target is not an allowlisted Google image URL."
                    )
                continue

            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type not in {"image/jpeg", "image/png"}:
                raise ValueError(f"Renderer returned unsupported content type {content_type!r}.")
            content_length = response.headers.get("content-length")
            try:
                declared_length = int(content_length) if content_length is not None else None
            except ValueError:
                declared_length = None
            if declared_length is not None and declared_length > max_bytes:
                raise ValueError(f"Renderer response exceeded {max_bytes} bytes.")

            data = bytearray()
            async for chunk in response.aiter_bytes():
                if len(data) + len(chunk) > max_bytes:
                    raise ValueError(f"Renderer response exceeded {max_bytes} bytes.")
                data.extend(chunk)
            return bytes(data), content_type, validated_url

    raise AssertionError("Renderer redirect loop exited unexpectedly.")


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    offset = 2
    start_of_frame = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            break
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(data):
            break
        if marker in start_of_frame:
            if segment_length < 7:
                break
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            if width <= 0 or height <= 0:
                break
            return width, height
        offset += segment_length
    raise ValueError("JPEG image response has no readable dimensions.")


def _format_number(value: float) -> str:
    numeric = float(value)
    return str(int(numeric)) if numeric.is_integer() else format(numeric, "g")
