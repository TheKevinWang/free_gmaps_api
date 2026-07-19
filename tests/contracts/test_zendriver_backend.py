from __future__ import annotations

from free_gmaps_api.backends.zendriver import ZendriverBackend


class _RecordingSession:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def stop(self) -> None:
        self._events.append("session.stop")


class _RecordingClient:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def aclose(self) -> None:
        self._events.append("client.aclose")


class _ClosedLoopClient:
    async def aclose(self) -> None:
        raise RuntimeError("Event loop is closed")


async def test_zendriver_backend_closes_http_client_before_browser_session() -> None:
    events: list[str] = []
    backend = object.__new__(ZendriverBackend)
    backend._session = _RecordingSession(events)  # type: ignore[assignment]
    backend._image_client = _RecordingClient(events)  # type: ignore[assignment]

    await backend.close()

    assert events == ["client.aclose", "session.stop"]


async def test_zendriver_backend_ignores_closed_loop_while_releasing_image_client() -> None:
    events: list[str] = []
    backend = object.__new__(ZendriverBackend)
    backend._session = _RecordingSession(events)  # type: ignore[assignment]
    backend._image_client = _ClosedLoopClient()  # type: ignore[assignment]

    await backend.close()

    assert events == ["session.stop"]
