from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from free_gmaps_api import __version__
from free_gmaps_api.backends.base import MapsBackend
from free_gmaps_api.http.backend import HttpBackend
from free_gmaps_api.routes import router, set_backend
from free_gmaps_api.settings import Settings


def create_app() -> FastAPI:
    settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        backend: MapsBackend
        if settings.backend == "http":
            backend = HttpBackend(settings)
        else:
            # Keep Zendriver imports out of the default process.  This import is
            # deliberately lazy so HTTP deployments need neither Chrome nor the
            # optional browser dependency.
            from free_gmaps_api.backends.zendriver import ZendriverBackend

            backend = ZendriverBackend(settings)
        set_backend(backend)
        try:
            yield
        finally:
            await backend.close()
            set_backend(None)

    app = FastAPI(
        title="Free Google Maps API",
        description=(
            "Independent experimental Google Maps web adapter with raw HTTP or explicit "
            "Zendriver backends. Use at your own risk and comply with applicable terms."
        ),
        version=__version__,
        lifespan=lifespan,
    )
    app.include_router(router)
    return app
