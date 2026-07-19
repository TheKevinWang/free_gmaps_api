from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from free_gmaps_api.browser.extract import (
    extract_coordinates_from_url,
    extract_dms_from_text,
    extract_orientation_from_url,
    extract_place_url_ids,
    extract_plus_code_from_text,
    extract_zoom_from_url,
)
from free_gmaps_api.browser.session import (
    BrowserSession,
    BrowserSessionError,
    ResponseCapture,
    _read_captured_responses,
    _save_screenshot,
)
from free_gmaps_api.settings import Settings


def test_extract_coordinates_from_at_url() -> None:
    url = "https://www.google.com/maps/@47.6205063,-122.3492774,3a,75y,210h,90t/data=..."
    coords = extract_coordinates_from_url(url)
    assert coords is not None
    lat, lng = coords
    assert abs(lat - 47.6205063) < 0.0001
    assert abs(lng - -122.3492774) < 0.0001


def test_extract_coordinates_from_viewpoint_url() -> None:
    url = "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=48.8584,2.2945"
    coords = extract_coordinates_from_url(url)
    assert coords is not None
    assert abs(coords[0] - 48.8584) < 0.0001


def test_extract_coordinates_none_when_absent() -> None:
    url = "https://www.google.com/maps/search/?api=1&query=test"
    assert extract_coordinates_from_url(url) is None


def test_extract_coordinates_from_maps_data_tokens() -> None:
    url = "https://www.google.com/maps/place/Eiffel+Tower/data=!3m1!4b1!3d48.8583701!4d2.2944813"
    assert extract_coordinates_from_url(url) == (48.8583701, 2.2944813)


def test_extract_zoom_from_url() -> None:
    url = "https://www.google.com/maps/@47.62,-122.35,14z"
    zoom = extract_zoom_from_url(url)
    assert zoom == 14.0


def test_extract_zoom_none_when_absent() -> None:
    url = "https://www.google.com/maps/search/?api=1&query=test"
    assert extract_zoom_from_url(url) is None


def test_extract_plus_code_from_text() -> None:
    text = "84VV+XW Seattle, Washington, USA"
    plus = extract_plus_code_from_text(text)
    assert plus is not None
    assert "+" in plus


def test_extract_plus_code_none_when_absent() -> None:
    text = "Space Needle, Seattle, WA"
    assert extract_plus_code_from_text(text) is None


def test_extract_dms_from_text() -> None:
    text = "47°37′13.8″N, 122°20′57.4″W"
    dms = extract_dms_from_text(text)
    assert dms is not None


def test_extract_orientation_from_url_heading_fov() -> None:
    url = "https://www.google.com/maps/@48.8584,2.2945,3a,80y,210h,90t/data=..."
    orient = extract_orientation_from_url(url)
    assert "heading" in orient
    assert orient["heading"] == 210.0
    assert "fov" in orient
    assert orient["fov"] == 80.0


def test_extract_orientation_from_query_params() -> None:
    url = "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=48.8584,2.2945&heading=210&pitch=0&fov=80"
    orient = extract_orientation_from_url(url)
    assert orient.get("heading") == 210.0
    assert orient.get("pitch") == 0.0
    assert orient.get("fov") == 80.0


def test_extract_place_url_ids() -> None:
    url = "https://www.google.com/maps/place/Space+Needle/@47.6205,-122.3493,15z/data=!4m6!3m5!1s0x5490152a0a7a7d0f:0x3f25f455a4f76f1!8m2!3d47.6205063!4d-122.3492774!16s%2Fg%2F1tf_9x0x"
    ids = extract_place_url_ids(url)
    assert isinstance(ids, list)


def test_extract_place_url_ids_empty_for_search_url() -> None:
    url = "https://www.google.com/maps/search/?api=1&query=test"
    ids = extract_place_url_ids(url)
    assert ids == []


async def test_optional_browser_capture_drops_oversized_cdp_body() -> None:
    expectation = SimpleNamespace(
        response=_value(
            SimpleNamespace(
                url="https://www.google.com/search", status=200, mime_type="application/json"
            )
        ),
        response_body=_value(("123456", False)),
    )
    capture = ResponseCapture("search", re.compile(".*"), max_bytes=5)

    assert await _read_captured_responses([(capture, expectation)]) == []


async def test_required_browser_capture_reports_oversized_cdp_body() -> None:
    expectation = SimpleNamespace(
        response=_value(
            SimpleNamespace(
                url="https://www.google.com/search", status=200, mime_type="application/json"
            )
        ),
        response_body=_value(("123456", False)),
    )
    capture = ResponseCapture("search", re.compile(".*"), max_bytes=5, required=True)

    with pytest.raises(BrowserSessionError, match="exceeded"):
        await _read_captured_responses([(capture, expectation)])


async def test_navigation_continues_when_initial_screenshot_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _FakePage(screenshot_failures={1})
    session = BrowserSession(
        Settings(
            artifact_dir=str(tmp_path),
            timeout_seconds=0.1,
            navigation_settle_seconds=0,
        )
    )
    monkeypatch.setattr(
        session,
        "_ensure_browser",
        AsyncMock(return_value=_FakeBrowser(page)),
    )

    result = await session.navigate("https://www.google.com/maps/search/test", request_id="shot")

    assert result["screenshot"] is None
    assert result["raw_visible_text"] == "before interaction"
    assert result["attempt"] == 1
    assert result["artifact_errors"] == ["screenshot.png: TimeoutError: CDP screenshot stalled"]
    artifact_dir = Path(str(result["artifact_dir"]))
    response = json.loads((artifact_dir / "response.json").read_text())
    assert response["artifacts"]["screenshot"] is None
    assert response["artifact_errors"] == result["artifact_errors"]
    browser_log = (artifact_dir / "browser.log").read_text()
    assert "optional artifact failure" in browser_log


async def test_interaction_capture_continues_when_interaction_screenshot_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _FakePage(screenshot_failures={2})
    session = BrowserSession(
        Settings(
            artifact_dir=str(tmp_path),
            timeout_seconds=0.1,
            navigation_settle_seconds=0,
            interaction_settle_seconds=0,
        )
    )
    monkeypatch.setattr(
        session,
        "_ensure_browser",
        AsyncMock(return_value=_FakeBrowser(page)),
    )

    async def interact(active_page: _FakePage) -> None:
        active_page.visible_text = "after interaction"

    result = await session.navigate(
        "https://www.google.com/maps/dir/test",
        request_id="interaction-shot",
        interaction=interact,
        interaction_name="details",
    )

    assert result["screenshot"] is not None
    assert result["interaction_screenshot"] is None
    assert result["interaction_error"] is None
    assert result["interaction_visible_text"] == "after interaction"
    assert result["artifact_errors"] == [
        "interaction-screenshot.png: TimeoutError: CDP screenshot stalled"
    ]


async def test_screenshot_timeout_consumes_late_completion_without_cancelling(
    tmp_path: Path,
) -> None:
    page = _LateScreenshotPage()
    tasks: set[asyncio.Task[Any]] = set()
    loop = asyncio.get_running_loop()
    loop_errors: list[dict[str, object]] = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
    try:
        screenshot, error = await _save_screenshot(
            page,
            tmp_path / "late.png",
            timeout_seconds=0.1,
            background_tasks=tasks,
        )
        assert screenshot is None
        assert error is not None and error.startswith("late.png: TimeoutError:")
        await asyncio.wait_for(page.completed.wait(), timeout=1.0)
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(old_handler)

    assert page.cancelled is False
    assert tasks == set()
    assert loop_errors == []


async def test_navigation_persists_capture_metadata_without_raw_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_body = "SENSITIVE_RAW_MAPS_BODY"
    page = _FakePage(screenshot_failures=set())
    page.response_body = raw_body
    session = BrowserSession(
        Settings(
            artifact_dir=str(tmp_path),
            timeout_seconds=0.1,
            navigation_settle_seconds=0,
        )
    )
    monkeypatch.setattr(
        session,
        "_ensure_browser",
        AsyncMock(return_value=_FakeBrowser(page)),
    )

    result = await session.navigate(
        "https://www.google.com/maps/search/test",
        request_id="capture-metadata",
        response_captures=(ResponseCapture("maps-place", re.compile(".*")),),
    )

    response_path = Path(str(result["response_path"]))
    serialized = response_path.read_text(encoding="utf-8")
    assert raw_body not in serialized
    response = json.loads(serialized)
    assert response["captured_responses"] == [
        {
            "name": "maps-place",
            "url_path": "/maps/preview/place",
            "status": 200,
            "content_type": "application/json",
            "bytes": len(raw_body),
        }
    ]


async def test_repeated_exact_url_reloads_without_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://www.google.com/maps/dir/repeated"
    page = _FakePage(screenshot_failures=set())
    page.url = url
    browser = _FakeBrowser(page)
    session = BrowserSession(
        Settings(
            artifact_dir=str(tmp_path),
            timeout_seconds=0.1,
            navigation_settle_seconds=0,
        )
    )
    monkeypatch.setattr(session, "_ensure_browser", AsyncMock(return_value=browser))

    result = await session.navigate(url, request_id="repeat")

    assert result["raw_visible_text"] == "before interaction"
    assert page.reload_calls == [True]
    assert page.ready_state_calls == ["complete"]
    assert page.lifecycle_events[:2] == ["reload", "ready:complete"]
    assert browser.get_calls == []


async def test_different_url_uses_browser_get(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _FakePage(screenshot_failures=set())
    browser = _FakeBrowser(page)
    session = BrowserSession(
        Settings(
            artifact_dir=str(tmp_path),
            timeout_seconds=0.1,
            navigation_settle_seconds=0,
        )
    )
    monkeypatch.setattr(session, "_ensure_browser", AsyncMock(return_value=browser))

    url = "https://www.google.com/maps/dir/different"
    await session.navigate(url, request_id="different")

    assert browser.get_calls == [url]
    assert page.reload_calls == []
    assert page.ready_state_calls == []


async def test_trace_setting_reports_missing_public_zendriver_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _FakePage(screenshot_failures=set())
    browser = _FakeBrowser(page)
    session = BrowserSession(
        Settings(
            artifact_dir=str(tmp_path),
            trace=True,
            timeout_seconds=0.1,
            navigation_settle_seconds=0,
        )
    )
    monkeypatch.setattr(session, "_ensure_browser", AsyncMock(return_value=browser))
    discard = AsyncMock()
    monkeypatch.setattr(session, "_discard_browser", discard)

    with pytest.raises(BrowserSessionError, match="installed public Zendriver"):
        await session.navigate("https://www.google.com/maps/search/test", request_id="trace")

    discard.assert_awaited_once()
    assert browser.get_calls == []


async def test_repeated_url_ready_state_stays_inside_navigation_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://www.google.com/maps/dir/stalled-reload"
    page = _FakePage(screenshot_failures=set())
    page.url = url
    page.ready_state_delay = 1.0
    browser = _FakeBrowser(page)
    session = BrowserSession(
        Settings(
            artifact_dir=str(tmp_path),
            timeout_seconds=0.1,
            navigation_settle_seconds=0,
        )
    )
    monkeypatch.setattr(session, "_ensure_browser", AsyncMock(return_value=browser))

    with pytest.raises(BrowserSessionError, match="failed after retry"):
        await session.navigate(url, request_id="stalled-repeat")

    assert page.reload_calls == [True, True]
    assert page.ready_state_calls == ["complete", "complete"]
    assert page.lifecycle_events == [
        "reload",
        "ready:complete",
        "reload",
        "ready:complete",
    ]


class _FakePage:
    def __init__(self, *, screenshot_failures: set[int]) -> None:
        self.url = "https://www.google.com/maps/place/test"
        self.visible_text = "before interaction"
        self._screenshot_failures = screenshot_failures
        self._screenshot_call = 0
        self.response_body = "{}"
        self.reload_calls: list[bool | None] = []
        self.ready_state_calls: list[str] = []
        self.ready_state_delay = 0.0
        self.lifecycle_events: list[str] = []

    async def set_window_size(self, *, width: int, height: int) -> None:
        del width, height

    async def save_screenshot(self, path: str, *, format: str) -> None:
        del path, format
        self._screenshot_call += 1
        if self._screenshot_call in self._screenshot_failures:
            raise TimeoutError("CDP screenshot stalled")

    async def evaluate(self, script: str) -> str:
        del script
        return self.visible_text

    async def reload(self, ignore_cache: bool | None = True) -> None:
        self.lifecycle_events.append("reload")
        self.reload_calls.append(ignore_cache)

    async def wait_for_ready_state(self, until: str) -> bool:
        self.lifecycle_events.append(f"ready:{until}")
        self.ready_state_calls.append(until)
        if self.ready_state_delay:
            await asyncio.sleep(self.ready_state_delay)
        return True

    async def select_all(self, selector: str) -> list[object]:
        del selector
        return []

    def expect_response(self, pattern: object) -> _FakeResponseContext:
        del pattern
        return _FakeResponseContext(self.response_body)


class _FakeResponseContext:
    def __init__(self, body: str) -> None:
        self.expectation = SimpleNamespace(
            response=_value(
                SimpleNamespace(
                    url="https://www.google.com/maps/preview/place",
                    status=200,
                    mime_type="application/json",
                )
            ),
            response_body=_value((body, False)),
        )

    async def __aenter__(self) -> object:
        return self.expectation

    async def __aexit__(self, *args: object) -> None:
        del args


class _LateScreenshotPage:
    def __init__(self) -> None:
        self.cancelled = False
        self.completed = asyncio.Event()

    async def save_screenshot(self, path: str, *, format: str) -> None:
        del path, format
        try:
            await asyncio.sleep(0.15)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.completed.set()


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self.main_tab = page
        self._page = page
        self.get_calls: list[str] = []

    async def get(self, url: str) -> _FakePage:
        self.get_calls.append(url)
        return self._page


async def _value(value: object) -> object:
    return value
