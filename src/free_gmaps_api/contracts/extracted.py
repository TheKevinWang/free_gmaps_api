from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from free_gmaps_api.contracts.envelope import UnsupportedField


class CoordinatePair(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    lat: float
    lng: float


# --- Street View ---


class LocationResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    display_text: str | None = None
    place_url: str | None = None
    coordinates: CoordinatePair | None = None
    source: str | None = None


class StreetViewOrientation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    heading: float | None = None
    pitch: float | None = None
    fov: float | None = None


class StreetViewScreenshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str
    width: int | None = None
    height: int | None = None


class StreetViewImage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str
    width: int | None = None
    height: int | None = None
    content_type: str | None = None
    source: Literal["web_renderer", "browser_screenshot"]
    clean: bool


class StreetViewExtracted(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    requested_location: str | None = None
    requested_pano: str | None = None
    requested_heading: float | None = None
    requested_pitch: float | None = None
    requested_fov: float | None = None
    location_resolution: LocationResolution | None = None
    requested_viewpoint: CoordinatePair | None = None
    resolved_url: str | None = None
    resolved_coordinates: CoordinatePair | None = None
    orientation: StreetViewOrientation | None = None
    title: str | None = None
    contributor: str | None = None
    capture_date: str | None = None
    image_key: str | None = None
    availability_message: str | None = None
    image: StreetViewImage | None = None
    screenshot: StreetViewScreenshot | None = None
    unsupported_api_fields: list[UnsupportedField] = Field(default_factory=list)


# --- Geocode ---


class GeocodeExtracted(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    input: str | None = None
    input_type: str | None = None
    formatted_address: str | None = None
    display_name: str | None = None
    coordinates: CoordinatePair | None = None
    plus_code: str | None = None
    place_url: str | None = None
    unsupported_api_fields: list[UnsupportedField] = Field(default_factory=list)


# --- Reverse Geocode ---


class ReverseGeocodeExtracted(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    input_coordinates: str
    display_coordinates_dms: str | None = None
    display_coordinates_decimal: str | None = None
    plus_code: str | None = None
    nearest_address_or_place: str | None = None
    place_url: str | None = None
    unsupported_api_fields: list[UnsupportedField] = Field(default_factory=list)


# --- Place ---


class PlaceExtracted(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: str | None = None
    name: str | None = None
    category: str | None = None
    rating: float | None = None
    review_count: int | None = None
    price_level_text: str | None = None
    address: str | None = None
    located_in: str | None = None
    hours_summary: str | None = None
    website: str | None = None
    phone: str | None = None
    plus_code: str | None = None
    place_detail_url: str | None = None
    coordinates: CoordinatePair | None = None
    official_place_id: str | None = None
    observed_maps_url_ids: list[str] = Field(default_factory=list)
    id_provenance: str | None = None
    unsupported_api_fields: list[UnsupportedField] = Field(default_factory=list)


# --- Directions ---


class DirectionsRouteStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    instruction: str
    distance_text: str | None = None
    distance_meters_approximate: int | None = None


class DirectionsRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str | None = None
    duration_text: str | None = None
    distance_text: str | None = None
    duration_seconds_approximate: int | None = None
    distance_meters_approximate: int | None = None
    label: str | None = None
    steps: list[DirectionsRouteStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DirectionsExtracted(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    origin: str | None = None
    destination: str | None = None
    resolved_origin: str | None = None
    resolved_destination: str | None = None
    travel_mode: str | None = None
    routes: list[DirectionsRoute] = Field(default_factory=list)
    selected_route: DirectionsRoute | None = None
    warnings: list[str] = Field(default_factory=list)
    unsupported_api_fields: list[UnsupportedField] = Field(default_factory=list)


# --- Map View ---


class MapViewExtracted(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    requested_center: str | None = None
    requested_zoom: int | None = None
    requested_basemap: str | None = None
    requested_layer: str | None = None
    resolved_url: str | None = None
    resolved_center: CoordinatePair | None = None
    resolved_zoom: float | None = None
    visible_controls: list[str] = Field(default_factory=list)
    screenshot: StreetViewScreenshot | None = None
    unsupported_api_fields: list[UnsupportedField] = Field(default_factory=list)


# --- Distance Matrix ---


class DistanceMatrixElement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: str
    distance_text: str | None = None
    duration_text: str | None = None
    route_summary: str | None = None
    travel_mode: str | None = None
    maps_url: str | None = None
    confidence_notes: list[str] = Field(default_factory=list)
    screenshot: str | None = None


class DistanceMatrixExtracted(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    origins: list[str] = Field(default_factory=list)
    destinations: list[str] = Field(default_factory=list)
    elements: list[list[DistanceMatrixElement]] = Field(default_factory=list)
    unsupported_api_fields: list[UnsupportedField] = Field(default_factory=list)


# --- Not Supported ---


class NotSupportedExtracted(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: str = "not_supported"
    message: str
    endpoint: str
