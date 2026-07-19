from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from free_gmaps_api.backends.base import MapsBackend
from free_gmaps_api.contracts.envelope import ApiEnvelope
from free_gmaps_api.contracts.extracted import (
    DirectionsExtracted,
    DistanceMatrixExtracted,
    GeocodeExtracted,
    MapViewExtracted,
    NotSupportedExtracted,
    PlaceExtracted,
    ReverseGeocodeExtracted,
    StreetViewExtracted,
)
from free_gmaps_api.contracts.requests import (
    DirectionsRequest,
    DistanceMatrixRequest,
    ElevationRequest,
    GeocodeRequest,
    MapViewRequest,
    PlaceDetailsRequest,
    PlaceSearchRequest,
    ReverseGeocodeRequest,
    StreetViewRequest,
    TimeZoneRequest,
)
from free_gmaps_api.services.unsupported import elevation_not_supported, time_zone_not_supported

router = APIRouter()

_backend: MapsBackend | None = None


def get_backend() -> MapsBackend:
    if _backend is None:
        raise RuntimeError("Maps backend not initialized.")
    return _backend


def set_backend(backend: MapsBackend | None) -> None:
    global _backend
    _backend = backend


BackendDep = Annotated[MapsBackend, Depends(get_backend)]


@router.get("/health")
async def health() -> dict[str, object]:
    from free_gmaps_api import __version__

    return {"ok": True, "version": __version__, "backend": _backend.name if _backend else None}


@router.post("/v1/street-view")
async def street_view(
    request: StreetViewRequest,
    backend: BackendDep,
) -> ApiEnvelope[StreetViewExtracted]:
    return await backend.street_view(request)


@router.post("/v1/geocode")
async def geocode(
    request: GeocodeRequest,
    backend: BackendDep,
) -> ApiEnvelope[GeocodeExtracted]:
    return await backend.geocode(request)


@router.post("/v1/reverse-geocode")
async def reverse_geocode(
    request: ReverseGeocodeRequest,
    backend: BackendDep,
) -> ApiEnvelope[ReverseGeocodeExtracted]:
    return await backend.reverse_geocode(request)


@router.post("/v1/place-search")
async def place_search(
    request: PlaceSearchRequest,
    backend: BackendDep,
) -> ApiEnvelope[PlaceExtracted]:
    return await backend.place_search(request)


@router.post("/v1/place-details")
async def place_details(
    request: PlaceDetailsRequest,
    backend: BackendDep,
) -> ApiEnvelope[PlaceExtracted]:
    return await backend.place_details(request)


@router.post("/v1/directions")
async def directions(
    request: DirectionsRequest,
    backend: BackendDep,
) -> ApiEnvelope[DirectionsExtracted]:
    return await backend.directions(request)


@router.post("/v1/map-view")
async def map_view(
    request: MapViewRequest,
    backend: BackendDep,
) -> ApiEnvelope[MapViewExtracted]:
    return await backend.map_view(request)


@router.post("/v1/distance-matrix")
async def distance_matrix(
    request: DistanceMatrixRequest,
    backend: BackendDep,
) -> ApiEnvelope[DistanceMatrixExtracted]:
    return await backend.distance_matrix(request)


@router.post("/v1/elevation")
async def elevation(request: ElevationRequest) -> ApiEnvelope[NotSupportedExtracted]:
    return elevation_not_supported(request)


@router.post("/v1/time-zone")
async def time_zone(request: TimeZoneRequest) -> ApiEnvelope[NotSupportedExtracted]:
    return time_zone_not_supported(request)
