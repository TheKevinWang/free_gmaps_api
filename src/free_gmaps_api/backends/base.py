from __future__ import annotations

from typing import Protocol

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


class MapsBackend(Protocol):
    """The eight browser-backed public operations plus process shutdown."""

    @property
    def name(self) -> str: ...

    async def street_view(self, request: StreetViewRequest) -> ApiEnvelope[StreetViewExtracted]: ...
    async def geocode(self, request: GeocodeRequest) -> ApiEnvelope[GeocodeExtracted]: ...
    async def reverse_geocode(
        self, request: ReverseGeocodeRequest
    ) -> ApiEnvelope[ReverseGeocodeExtracted]: ...
    async def place_search(self, request: PlaceSearchRequest) -> ApiEnvelope[PlaceExtracted]: ...
    async def place_details(self, request: PlaceDetailsRequest) -> ApiEnvelope[PlaceExtracted]: ...
    async def directions(self, request: DirectionsRequest) -> ApiEnvelope[DirectionsExtracted]: ...
    async def map_view(self, request: MapViewRequest) -> ApiEnvelope[MapViewExtracted]: ...
    async def distance_matrix(
        self, request: DistanceMatrixRequest
    ) -> ApiEnvelope[DistanceMatrixExtracted]: ...
    async def close(self) -> None: ...
