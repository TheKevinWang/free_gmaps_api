from __future__ import annotations

import re
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from free_gmaps_api.maps_urls.directions import build_directions_url
from free_gmaps_api.maps_urls.map_view import build_map_view_url
from free_gmaps_api.maps_urls.search import build_search_url
from free_gmaps_api.maps_urls.street_view import build_street_view_url

MAX_INPUT_LENGTH = 512
MAX_SHORT_INPUT_LENGTH = 128
MAX_MAPS_URL_LENGTH = 2048
MAX_FILTER_ITEMS = 25
MAX_WAYPOINTS = 10
MAX_MATRIX_AXIS = 10
MAX_MATRIX_ELEMENTS = 25
MAX_VIEWPORT_DIMENSION = 4096
MAX_VIEWPORT_PIXELS = 3840 * 2160
MAX_STREET_VIEW_DIMENSION = 2048
MAX_STREET_VIEW_PIXELS = 2048 * 2048

InputText = Annotated[str, StringConstraints(max_length=MAX_INPUT_LENGTH)]
ShortInputText = Annotated[str, StringConstraints(max_length=MAX_SHORT_INPUT_LENGTH)]
MapsUrlText = Annotated[str, StringConstraints(max_length=MAX_MAPS_URL_LENGTH)]


class ViewportSize(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    width: int = Field(ge=1, le=MAX_VIEWPORT_DIMENSION)
    height: int = Field(ge=1, le=MAX_VIEWPORT_DIMENSION)

    @model_validator(mode="after")
    def validate_pixel_count(self) -> Self:
        if self.width * self.height > MAX_VIEWPORT_PIXELS:
            raise ValueError(f"Viewport may contain at most {MAX_VIEWPORT_PIXELS} pixels.")
        return self


class StreetViewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: InputText | None = None
    pano: InputText | None = None
    heading: float | None = Field(default=None, ge=0, le=360, allow_inf_nan=False)
    pitch: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    fov: float | None = Field(default=None, ge=10, le=120, allow_inf_nan=False)
    size: str | None = None
    viewport: ViewportSize | None = None
    unsupported_api_fields: list[ShortInputText] = Field(
        default_factory=list, max_length=MAX_FILTER_ITEMS
    )

    @field_validator("size")
    @classmethod
    def validate_size(cls, value: str | None) -> str | None:
        if value is not None:
            match = re.fullmatch(r"(\d+)x(\d+)", value.strip())
            if match is None:
                raise ValueError(
                    "Street View size must use positive WIDTHxHEIGHT dimensions, "
                    "for example 640x360."
                )
            width, height = int(match.group(1)), int(match.group(2))
            if width <= 0 or height <= 0:
                raise ValueError(
                    "Street View size must use positive WIDTHxHEIGHT dimensions, "
                    "for example 640x360."
                )
            if width > MAX_STREET_VIEW_DIMENSION or height > MAX_STREET_VIEW_DIMENSION:
                raise ValueError(
                    "Street View dimensions may not exceed "
                    f"{MAX_STREET_VIEW_DIMENSION} pixels per side."
                )
            if width * height > MAX_STREET_VIEW_PIXELS:
                raise ValueError(
                    f"Street View images may contain at most {MAX_STREET_VIEW_PIXELS} pixels."
                )
            return value.strip()
        return None

    @model_validator(mode="after")
    def validate_maps_urls(self) -> Self:
        location = self.location.strip() if self.location is not None else None
        coordinate_location = bool(
            location and re.fullmatch(r"-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?", location)
        )
        if location and not coordinate_location:
            build_search_url(location)
        elif coordinate_location or self.pano is not None:
            build_street_view_url(
                viewpoint=location if coordinate_location else None,
                heading=self.heading,
                pitch=self.pitch,
                fov=self.fov,
                pano=self.pano,
            )
        return self


class GeocodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: InputText | None = None
    place_id: InputText | None = None
    bounds: InputText | None = None
    region: ShortInputText | None = None
    language: ShortInputText | None = None
    components: InputText | None = None
    result_type: list[ShortInputText] = Field(default_factory=list, max_length=MAX_FILTER_ITEMS)
    location_type: list[ShortInputText] = Field(default_factory=list, max_length=MAX_FILTER_ITEMS)

    @model_validator(mode="after")
    def validate_maps_url(self) -> Self:
        query = self.address or (f"place_id:{self.place_id}" if self.place_id else None)
        if query:
            build_search_url(query, self.place_id)
        return self


class ReverseGeocodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latlng: InputText
    result_type: list[ShortInputText] = Field(default_factory=list, max_length=MAX_FILTER_ITEMS)
    location_type: list[ShortInputText] = Field(default_factory=list, max_length=MAX_FILTER_ITEMS)
    language: ShortInputText | None = None
    region: ShortInputText | None = None

    @model_validator(mode="after")
    def validate_maps_url(self) -> Self:
        build_search_url(self.latlng)
        return self


class PlaceSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: InputText
    location_bias: InputText | None = None
    location_restriction: InputText | None = None
    included_type: ShortInputText | None = None
    open_now: bool | None = None
    price_levels: list[ShortInputText] = Field(default_factory=list, max_length=MAX_FILTER_ITEMS)
    language: ShortInputText | None = None
    region: ShortInputText | None = None
    fields: list[ShortInputText] = Field(default_factory=list, max_length=MAX_FILTER_ITEMS)

    @model_validator(mode="after")
    def validate_maps_url(self) -> Self:
        build_search_url(self.query)
        return self


class PlaceDetailsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_id: InputText | None = None
    maps_url: MapsUrlText | None = None
    query: InputText | None = None
    fields: list[ShortInputText] = Field(default_factory=list, max_length=MAX_FILTER_ITEMS)
    language: ShortInputText | None = None
    region: ShortInputText | None = None

    @model_validator(mode="after")
    def validate_maps_url_length(self) -> Self:
        if self.query:
            build_search_url(self.query, self.place_id)
        elif self.place_id:
            build_search_url(f"place_id:{self.place_id}", self.place_id)
        return self


class DirectionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: InputText
    destination: InputText
    travel_mode: ShortInputText = "driving"
    waypoints: list[InputText] = Field(default_factory=list, max_length=MAX_WAYPOINTS)
    avoid: list[ShortInputText] = Field(default_factory=list, max_length=MAX_FILTER_ITEMS)
    alternatives: bool = False
    units: ShortInputText | None = None
    language: ShortInputText | None = None
    region: ShortInputText | None = None
    departure_time: ShortInputText | None = None
    arrival_time: ShortInputText | None = None
    optimize_waypoints: bool = False
    traffic_model: ShortInputText | None = None
    transit_mode: list[ShortInputText] = Field(default_factory=list, max_length=MAX_FILTER_ITEMS)
    transit_routing_preference: ShortInputText | None = None

    @model_validator(mode="after")
    def validate_maps_url(self) -> Self:
        build_directions_url(
            self.origin,
            self.destination,
            self.travel_mode,
            self.waypoints,
            self.avoid,
        )
        return self


class MapViewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    center: InputText
    zoom: int | None = Field(default=None, ge=0, le=21)
    basemap: ShortInputText | None = None
    layer: ShortInputText | None = None
    viewport: ViewportSize | None = None

    @model_validator(mode="after")
    def validate_maps_url(self) -> Self:
        build_map_view_url(self.center, self.zoom, self.basemap, self.layer)
        return self


class DistanceMatrixRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origins: list[InputText] = Field(min_length=1, max_length=MAX_MATRIX_AXIS)
    destinations: list[InputText] = Field(min_length=1, max_length=MAX_MATRIX_AXIS)
    travel_mode: ShortInputText = "driving"
    avoid: list[ShortInputText] = Field(default_factory=list, max_length=MAX_FILTER_ITEMS)
    units: ShortInputText | None = None
    language: ShortInputText | None = None
    region: ShortInputText | None = None
    departure_time: ShortInputText | None = None
    arrival_time: ShortInputText | None = None
    traffic_model: ShortInputText | None = None
    transit_mode: list[ShortInputText] = Field(default_factory=list, max_length=MAX_FILTER_ITEMS)
    transit_routing_preference: ShortInputText | None = None

    @model_validator(mode="after")
    def validate_workload_and_urls(self) -> Self:
        element_count = len(self.origins) * len(self.destinations)
        if element_count > MAX_MATRIX_ELEMENTS:
            raise ValueError(
                f"Distance matrix may contain at most {MAX_MATRIX_ELEMENTS} elements; "
                f"received {element_count}."
            )
        for origin in self.origins:
            for destination in self.destinations:
                build_directions_url(
                    origin,
                    destination,
                    self.travel_mode,
                    avoid=self.avoid,
                )
        return self


class ElevationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locations: list[InputText] = Field(default_factory=list, max_length=MAX_FILTER_ITEMS)
    path: list[InputText] = Field(default_factory=list, max_length=MAX_FILTER_ITEMS)
    samples: int | None = Field(default=None, ge=1, le=512)


class TimeZoneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: InputText
    timestamp: int | None = Field(default=None, ge=0)
    language: ShortInputText | None = None
