from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObservedCoordinates:
    lat: float
    lng: float


@dataclass(frozen=True)
class ObservedPlace:
    name: str | None = None
    address: str | None = None
    coordinates: ObservedCoordinates | None = None
    official_place_id: str | None = None
    canonical_url: str | None = None
    category: str | None = None
    rating: float | None = None
    review_count: int | None = None
    match_basis: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObservedRoute:
    duration_text: str
    distance_text: str
    label: str | None = None
    summary: str | None = None
