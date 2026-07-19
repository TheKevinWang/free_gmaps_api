from __future__ import annotations

from typing import Literal

import httpx

from free_gmaps_api.browser.session import BrowserSession
from free_gmaps_api.contracts.envelope import ApiEnvelope
from free_gmaps_api.contracts.extracted import (
    DirectionsExtracted,
    DistanceMatrixExtracted,
    GeocodeExtracted,
    MapViewExtracted,
    PlaceExtracted,
    ReverseGeocodeExtracted,
    StreetViewExtracted,
)
from free_gmaps_api.contracts.requests import (
    DirectionsRequest,
    DistanceMatrixRequest,
    GeocodeRequest,
    MapViewRequest,
    PlaceDetailsRequest,
    PlaceSearchRequest,
    ReverseGeocodeRequest,
    StreetViewRequest,
)
from free_gmaps_api.services.directions import run_directions
from free_gmaps_api.services.distance_matrix import run_distance_matrix
from free_gmaps_api.services.geocode import run_geocode, run_reverse_geocode
from free_gmaps_api.services.map_view import run_map_view
from free_gmaps_api.services.place import run_place_details, run_place_search
from free_gmaps_api.services.street_view import run_street_view
from free_gmaps_api.settings import Settings


class ZendriverBackend:
    """Compatibility adapter for the pre-HTTP browser services."""

    @property
    def name(self) -> Literal["zendriver"]:
        return "zendriver"

    def __init__(self, settings: Settings) -> None:
        self._session = BrowserSession(settings)
        self._image_client = httpx.AsyncClient(
            proxy=settings.proxy_url,
            follow_redirects=False,
            timeout=settings.timeout_seconds,
            headers={"Referer": "https://www.google.com/"},
        )

    async def street_view(self, request: StreetViewRequest) -> ApiEnvelope[StreetViewExtracted]:
        return await run_street_view(request, self._session, image_client=self._image_client)

    async def geocode(self, request: GeocodeRequest) -> ApiEnvelope[GeocodeExtracted]:
        return await run_geocode(request, self._session)

    async def reverse_geocode(
        self, request: ReverseGeocodeRequest
    ) -> ApiEnvelope[ReverseGeocodeExtracted]:
        return await run_reverse_geocode(request, self._session)

    async def place_search(self, request: PlaceSearchRequest) -> ApiEnvelope[PlaceExtracted]:
        return await run_place_search(request, self._session)

    async def place_details(self, request: PlaceDetailsRequest) -> ApiEnvelope[PlaceExtracted]:
        return await run_place_details(request, self._session)

    async def directions(self, request: DirectionsRequest) -> ApiEnvelope[DirectionsExtracted]:
        return await run_directions(request, self._session)

    async def map_view(self, request: MapViewRequest) -> ApiEnvelope[MapViewExtracted]:
        return await run_map_view(request, self._session)

    async def distance_matrix(
        self, request: DistanceMatrixRequest
    ) -> ApiEnvelope[DistanceMatrixExtracted]:
        return await run_distance_matrix(request, self._session)

    async def close(self) -> None:
        try:
            # Zendriver may close its Proactor event loop while stopping Chrome.
            # The proxied HTTP client must therefore release its TLS connection
            # before stopping the browser session.
            try:
                await self._image_client.aclose()
            except RuntimeError as exc:
                # Zendriver's process-exit callback can close the event loop before
                # pytest's async fixture teardown.  At that point no async cleanup
                # can run; process shutdown will release the remaining socket.
                if str(exc) != "Event loop is closed":
                    raise
        finally:
            await self._session.stop()
