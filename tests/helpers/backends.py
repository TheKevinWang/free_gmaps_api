from __future__ import annotations

from free_gmaps_api.backends.base import MapsBackend
from free_gmaps_api.http.backend import HttpBackend
from free_gmaps_api.settings import Settings


def build_test_backend(settings: Settings) -> MapsBackend:
    if settings.backend == "http":
        return HttpBackend(settings)
    from free_gmaps_api.backends.zendriver import ZendriverBackend

    return ZendriverBackend(settings)
