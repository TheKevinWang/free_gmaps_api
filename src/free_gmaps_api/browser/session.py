from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
import tempfile
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from free_gmaps_api.browser.artifacts import make_artifact_dir
from free_gmaps_api.settings import Settings


class BrowserSessionError(Exception):
    pass


NavigationInteraction = Callable[[Any], Awaitable[None]]


@dataclass(frozen=True)
class ResponseCapture:
    name: str
    url_pattern: re.Pattern[str]
    max_bytes: int = 2 * 1024 * 1024
    required: bool = False


@dataclass(frozen=True)
class CapturedResponse:
    name: str
    url_path: str
    status: int
    content_type: str
    body: bytes


class BrowserSession:
    """Manage serialized, recoverable Zendriver browser navigation."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._browser: Any | None = None
        self._profile_dir: tempfile.TemporaryDirectory[str] | None = None
        self._lock = asyncio.Lock()
        self._artifact_base = Path(settings.artifact_dir)
        self._artifact_tasks: set[asyncio.Task[Any]] = set()
        self._stopped = False

    @property
    def timeout_seconds(self) -> float:
        return self._settings.timeout_seconds

    async def _ensure_browser(self) -> Any:
        if self._browser is not None and _browser_is_usable(self._browser):
            return self._browser
        await self._discard_browser()
        try:
            import zendriver as zd

            self._profile_dir = tempfile.TemporaryDirectory(prefix="free-gmaps-api-")
            config = zd.Config(
                user_data_dir=self._profile_dir.name,
                headless=self._settings.headless,
                browser_args=[
                    f"--lang={self._settings.locale}",
                    f"--proxy-server={self._settings.proxy_url}",
                ],
                no_activate=not self._settings.headless,
            )
            self._browser = await zd.start(config=config)
        except Exception as exc:
            await self._discard_browser()
            raise BrowserSessionError(f"Failed to start browser: {exc}") from exc
        return self._browser

    async def navigate(
        self,
        url: str,
        request_id: str | None = None,
        viewport: tuple[int, int] | None = None,
        interaction: NavigationInteraction | None = None,
        interaction_name: str | None = None,
        response_captures: tuple[ResponseCapture, ...] = (),
    ) -> dict[str, object]:
        artifact_dir = make_artifact_dir(self._artifact_base, request_id)
        async with self._lock:
            if self._stopped:
                raise BrowserSessionError("Browser session has been stopped.")

            errors: list[str] = []
            for attempt in range(2):
                browser = await self._ensure_browser()
                if self._settings.trace and not _browser_supports_playwright_trace(browser):
                    await self._discard_browser()
                    raise BrowserSessionError(
                        "GMAPS_TRACE=true requires Zendriver methods "
                        "start_playwright_trace() and stop_playwright_trace(); "
                        "the installed public Zendriver does not provide them."
                    )
                trace_name = "trace" if attempt == 0 else "trace-retry"
                trace_started = False
                trace_path: str | None = None
                interaction_error: str | None = None
                interaction_current_url: str | None = None
                interaction_screenshot_path: str | None = None
                interaction_visible_text: str | None = None
                interaction_visible_text_path: str | None = None
                interaction_accessibility_path: str | None = None
                artifact_errors: list[str] = []
                try:
                    if self._settings.trace:
                        await browser.start_playwright_trace(
                            traces_dir=artifact_dir,
                            name=trace_name,
                            title=f"Navigate to {url}",
                            tab=browser.main_tab,
                        )
                        trace_started = True

                    async with contextlib.AsyncExitStack() as stack:
                        capture_expectations: list[tuple[ResponseCapture, Any]] = []
                        for capture in response_captures:
                            expectation = await stack.enter_async_context(
                                browser.main_tab.expect_response(capture.url_pattern)
                            )
                            capture_expectations.append((capture, expectation))
                        metadata_expectation = None
                        if "map_action=pano" in url:
                            metadata_expectation = await stack.enter_async_context(
                                browser.main_tab.expect_response(
                                    re.compile(r"https://www\.google\.com/maps/photometa/si/v1\?.*")
                                )
                            )

                        async with asyncio.timeout(self._settings.timeout_seconds):
                            active_page = browser.main_tab
                            if str(getattr(active_page, "url", "")) == url:
                                page = active_page
                                await page.reload(ignore_cache=True)
                                await page.wait_for_ready_state("complete")
                            else:
                                page = await browser.get(url)
                            if viewport is not None:
                                await page.set_window_size(width=viewport[0], height=viewport[1])
                            await asyncio.sleep(self._settings.navigation_settle_seconds)
                        current_url = str(page.url)
                        screenshot_path, screenshot_error = await _save_screenshot(
                            page,
                            artifact_dir / "screenshot.png",
                            timeout_seconds=self._settings.timeout_seconds,
                            background_tasks=self._artifact_tasks,
                        )
                        if screenshot_error is not None:
                            artifact_errors.append(screenshot_error)
                            _record_artifact_error(
                                artifact_dir,
                                screenshot_error,
                                attempt=attempt + 1,
                            )
                        raw_text = await _get_visible_text(page)
                        visible_text_path = artifact_dir / "visible-text.txt"
                        visible_text_path.write_text(raw_text, encoding="utf-8")
                        accessibility_path = await _write_accessibility_tree(page, artifact_dir)

                        if interaction is not None:
                            try:
                                async with asyncio.timeout(self._settings.timeout_seconds):
                                    await interaction(page)
                                    await asyncio.sleep(self._settings.interaction_settle_seconds)
                                interaction_current_url = str(page.url)
                                (
                                    interaction_screenshot_path,
                                    interaction_screenshot_error,
                                ) = await _save_screenshot(
                                    page,
                                    artifact_dir / "interaction-screenshot.png",
                                    timeout_seconds=self._settings.timeout_seconds,
                                    background_tasks=self._artifact_tasks,
                                )
                                if interaction_screenshot_error is not None:
                                    artifact_errors.append(interaction_screenshot_error)
                                    _record_artifact_error(
                                        artifact_dir,
                                        interaction_screenshot_error,
                                        attempt=attempt + 1,
                                    )
                                interaction_visible_text = await _get_visible_text(page)
                                interaction_text_path = (
                                    artifact_dir / "interaction-visible-text.txt"
                                )
                                interaction_text_path.write_text(
                                    interaction_visible_text,
                                    encoding="utf-8",
                                )
                                interaction_visible_text_path = str(interaction_text_path)
                                interaction_accessibility_path = await _write_accessibility_tree(
                                    page,
                                    artifact_dir,
                                    filename="interaction-accessibility.json",
                                )
                            except Exception as exc:
                                interaction_error = f"{type(exc).__name__}: {exc}"

                        candidate_urls = await _get_candidate_maps_urls(page)
                        captured_responses = await _read_captured_responses(capture_expectations)
                        metadata_body = await _read_expected_body(metadata_expectation)
                        metadata_path: str | None = None
                        if metadata_body is not None:
                            path = artifact_dir / "street-view-metadata.txt"
                            path.write_text(metadata_body, encoding="utf-8")
                            metadata_path = str(path)

                    if trace_started:
                        trace_path = await _stop_trace(browser)
                        trace_started = False

                    request_path = artifact_dir / "request.json"
                    request_path.write_text(
                        json.dumps(
                            {
                                "url": url,
                                "viewport": list(viewport) if viewport is not None else None,
                                "interaction": interaction_name,
                                "response_captures": [
                                    capture.name for capture in response_captures
                                ],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    response_path = artifact_dir / "response.json"
                    response_path.write_text(
                        json.dumps(
                            {
                                "current_url": current_url,
                                "interaction_current_url": interaction_current_url,
                                "candidate_maps_urls": candidate_urls,
                                "attempt": attempt + 1,
                                "recovered_errors": errors,
                                "interaction_error": interaction_error,
                                "artifact_errors": artifact_errors,
                                "captured_responses": [
                                    {
                                        "name": captured.name,
                                        "url_path": captured.url_path,
                                        "status": captured.status,
                                        "content_type": captured.content_type,
                                        "bytes": len(captured.body),
                                    }
                                    for captured in captured_responses
                                ],
                                "artifacts": {
                                    "screenshot": screenshot_path,
                                    "raw_visible_text": str(visible_text_path),
                                    "accessibility": accessibility_path,
                                    "interaction_screenshot": interaction_screenshot_path,
                                    "interaction_visible_text": interaction_visible_text_path,
                                    "interaction_accessibility": (interaction_accessibility_path),
                                    "street_view_metadata": metadata_path,
                                    "trace": trace_path,
                                },
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    return {
                        "current_url": current_url,
                        "interaction_current_url": interaction_current_url,
                        "candidate_maps_urls": candidate_urls,
                        "screenshot": screenshot_path,
                        "raw_visible_text": raw_text,
                        "visible_text_path": str(visible_text_path),
                        "accessibility_path": accessibility_path,
                        "interaction_screenshot": interaction_screenshot_path,
                        "interaction_visible_text": interaction_visible_text,
                        "interaction_visible_text_path": interaction_visible_text_path,
                        "interaction_accessibility_path": interaction_accessibility_path,
                        "interaction_error": interaction_error,
                        "artifact_errors": artifact_errors,
                        "captured_responses": captured_responses,
                        "street_view_metadata": metadata_path,
                        "street_view_metadata_body": metadata_body,
                        "trace_path": trace_path,
                        "response_path": str(response_path),
                        "artifact_dir": str(artifact_dir),
                        "attempt": attempt + 1,
                        "recovered_errors": errors,
                        "page": page,
                    }
                except Exception as exc:
                    if trace_started:
                        with contextlib.suppress(Exception):
                            trace_path = await _stop_trace(browser)
                    error_message = f"{type(exc).__name__}: {exc}"
                    errors.append(error_message)
                    _record_error(artifact_dir, exc, attempt=attempt + 1, trace_path=trace_path)
                    await self._discard_browser()
                    if attempt == 0:
                        continue
                    raise BrowserSessionError(
                        f"Browser operation failed after retry: {exc}. Artifacts: {artifact_dir}"
                    ) from exc

            raise AssertionError("Browser navigation retry loop exited unexpectedly.")

    async def _discard_browser(self) -> None:
        browser, self._browser = self._browser, None
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.stop()
        await _drain_background_tasks(self._artifact_tasks)
        profile_dir, self._profile_dir = self._profile_dir, None
        if profile_dir is not None:
            with contextlib.suppress(Exception):
                profile_dir.cleanup()

    async def stop(self) -> None:
        async with self._lock:
            self._stopped = True
            await self._discard_browser()


def _browser_is_usable(browser: Any) -> bool:
    if bool(getattr(browser, "stopped", True)):
        return False
    connection = getattr(browser, "connection", None)
    return connection is not None and bool(getattr(connection, "running", False))


def _browser_supports_playwright_trace(browser: Any) -> bool:
    return callable(getattr(browser, "start_playwright_trace", None)) and callable(
        getattr(browser, "stop_playwright_trace", None)
    )


async def _stop_trace(browser: Any) -> str | None:
    artifacts = await browser.stop_playwright_trace(archive=True)
    archive_file = getattr(artifacts, "archive_file", None)
    return str(archive_file) if archive_file is not None else None


async def _save_screenshot(
    page: Any,
    path: Path,
    *,
    timeout_seconds: float,
    background_tasks: set[asyncio.Task[Any]] | None = None,
) -> tuple[str | None, str | None]:
    """Capture optional screenshot evidence without failing successful navigation."""

    tasks = background_tasks if background_tasks is not None else set()
    task = asyncio.create_task(page.save_screenshot(str(path), format="png"))
    tasks.add(task)
    task.add_done_callback(lambda completed: _consume_background_task(completed, tasks))
    try:
        timeout = min(5.0, max(0.1, timeout_seconds))
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        return str(path), None
    except Exception as exc:
        return None, f"{path.name}: {type(exc).__name__}: {exc}"


def _consume_background_task(task: asyncio.Task[Any], tasks: set[asyncio.Task[Any]]) -> None:
    tasks.discard(task)
    with contextlib.suppress(BaseException):
        task.result()


async def _drain_background_tasks(tasks: set[asyncio.Task[Any]]) -> None:
    """Consume optional artifact work after its browser connection is stopped."""

    pending = list(tasks)
    if not pending:
        return
    _, still_pending = await asyncio.wait(pending, timeout=1.0)
    for task in still_pending:
        task.cancel()
    if still_pending:
        await asyncio.gather(*still_pending, return_exceptions=True)


async def _get_visible_text(page: Any) -> str:
    try:
        text: str = await page.evaluate("document.body.innerText")
        return text
    except Exception:
        return ""


async def _read_expected_body(expectation: Any | None) -> str | None:
    if expectation is None:
        return None
    try:
        body, is_base64 = await asyncio.wait_for(expectation.response_body, timeout=5.0)
        if is_base64:
            return base64.b64decode(body).decode("utf-8", errors="replace")
        return str(body)
    except Exception:
        return None


async def _read_captured_responses(
    expectations: list[tuple[ResponseCapture, Any]],
) -> list[CapturedResponse]:
    """Read matched bodies and retain only bounded responses.

    CDP's Network.getResponseBody returns the completed body as one value, so
    the limit prevents oversized bodies from being retained or propagated but
    cannot stop Chrome from receiving the response.  HTTP mode uses true
    streaming limits; browser mode records this narrower guarantee explicitly.
    """
    captured: list[CapturedResponse] = []
    for specification, expectation in expectations:
        try:
            timeout = 5.0 if specification.required else 0.25
            response = await asyncio.wait_for(expectation.response, timeout=timeout)
            body_text, is_base64 = await asyncio.wait_for(expectation.response_body, timeout=5.0)
            body = base64.b64decode(body_text) if is_base64 else str(body_text).encode("utf-8")
            if len(body) > specification.max_bytes:
                if specification.required:
                    raise BrowserSessionError(
                        f"Captured response {specification.name!r} exceeded "
                        f"{specification.max_bytes} bytes."
                    )
                continue
            captured.append(
                CapturedResponse(
                    name=specification.name,
                    url_path=urlsplit(str(response.url)).path,
                    status=int(response.status),
                    content_type=str(response.mime_type or "").lower(),
                    body=body,
                )
            )
        except BrowserSessionError:
            raise
        except Exception as exc:
            if specification.required:
                raise BrowserSessionError(
                    f"Required response {specification.name!r} was not captured."
                ) from exc
    return captured


async def _write_accessibility_tree(
    page: Any,
    artifact_dir: Path,
    *,
    filename: str = "accessibility.json",
) -> str | None:
    try:
        elements = await page.select_all("[role],button,input,a")
        nodes = []
        for element in elements[:500]:
            attrs = element.attrs
            nodes.append(
                {
                    "tag": str(getattr(element, "tag", "")),
                    "role": attrs.get("role"),
                    "name": attrs.get("aria-label") or attrs.get("title"),
                    "text": str(element.text).strip()[:500],
                    "href": attrs.get("href"),
                }
            )
        path = artifact_dir / filename
        path.write_text(
            json.dumps(nodes, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return str(path)
    except Exception:
        return None


async def _get_candidate_maps_urls(page: Any) -> list[str]:
    try:
        links = await page.select_all("a[href]")
        urls: list[str] = []
        for link in links:
            href = link.attrs.get("href")
            if not href:
                continue
            decoded = unquote(str(href))
            if "google.com/maps/" in decoded:
                urls.append(decoded)
        return list(dict.fromkeys(urls))[:100]
    except Exception:
        return []


def _record_error(
    artifact_dir: Path,
    exc: Exception,
    *,
    attempt: int,
    trace_path: str | None,
) -> None:
    error_path = artifact_dir / "browser.log"
    with contextlib.suppress(Exception), error_path.open("a", encoding="utf-8") as stream:
        stream.write(f"Attempt {attempt}\n")
        stream.write(f"Trace: {trace_path or 'unavailable'}\n")
        stream.writelines(traceback.format_exception(type(exc), exc, exc.__traceback__))
        stream.write("\n")


def _record_artifact_error(artifact_dir: Path, message: str, *, attempt: int) -> None:
    error_path = artifact_dir / "browser.log"
    with contextlib.suppress(Exception), error_path.open("a", encoding="utf-8") as stream:
        stream.write(f"Attempt {attempt} optional artifact failure\n")
        stream.write(f"{message}\n\n")


def parse_latlng_from_url(url: str) -> tuple[float, float] | None:
    match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if match:
        return float(match.group(1)), float(match.group(2))
    match2 = re.search(r"viewpoint=(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if match2:
        return float(match2.group(1)), float(match2.group(2))
    return None


def parse_orientation_from_url(url: str) -> dict[str, float]:
    result: dict[str, float] = {}
    h = re.search(r"[,/](\d+\.?\d*)h(?=[,/])", url)
    if h:
        result["heading"] = float(h.group(1))
    heading_param = re.search(r"heading=(-?\d+\.?\d*)", url)
    if heading_param:
        result["heading"] = float(heading_param.group(1))
    p = re.search(r"[,/](-?\d+\.?\d*)t(?=[,/])", url)
    if p:
        result["pitch"] = float(p.group(1))
    pitch_param = re.search(r"pitch=(-?\d+\.?\d*)", url)
    if pitch_param:
        result["pitch"] = float(pitch_param.group(1))
    fov_param = re.search(r"fov=(-?\d+\.?\d*)", url)
    if fov_param:
        result["fov"] = float(fov_param.group(1))
    y = re.search(r"[,/](\d+\.?\d*)y(?=[,/])", url)
    if y:
        result["fov"] = float(y.group(1))
    return result
