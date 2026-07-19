from __future__ import annotations

import pytest
from pydantic import ValidationError

from free_gmaps_api.contracts.envelope import (
    ArtifactSet,
    Confidence,
    ExtractedField,
    UnsupportedField,
)
from free_gmaps_api.contracts.extracted import (
    CoordinatePair,
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
    MAX_INPUT_LENGTH,
    MAX_MATRIX_ELEMENTS,
    MAX_STREET_VIEW_DIMENSION,
    MAX_VIEWPORT_DIMENSION,
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
    ViewportSize,
)


def test_extracted_field_with_provenance() -> None:
    f: ExtractedField[str] = ExtractedField(value="test", source="url", confidence="high")
    assert f.value == "test"
    assert f.source == "url"


def test_unsupported_field() -> None:
    u = UnsupportedField(field="optimize_waypoints", reason="Not supported", requested_value=True)
    assert u.field == "optimize_waypoints"


def test_artifact_set_defaults() -> None:
    a = ArtifactSet()
    assert a.screenshot is None
    assert a.trace is None
    assert a.accessibility is None
    assert a.response is None


def test_confidence_model() -> None:
    c = Confidence(overall="medium", notes=["partial result"])
    assert c.overall == "medium"


def test_street_view_request_full() -> None:
    r = StreetViewRequest(
        location="Eiffel Tower Paris",
        heading=210.0,
        pitch=0.0,
        fov=80.0,
        viewport=ViewportSize(width=1280, height=720),
    )
    assert r.location == "Eiffel Tower Paris"
    assert r.heading == 210.0


def test_street_view_request_coordinate_location() -> None:
    r = StreetViewRequest(location="48.8584,2.2945")
    assert r.location == "48.8584,2.2945"


def test_geocode_request() -> None:
    r = GeocodeRequest(address="Space Needle Seattle WA")
    assert r.address == "Space Needle Seattle WA"
    assert r.place_id is None


def test_reverse_geocode_request() -> None:
    r = ReverseGeocodeRequest(latlng="47.6205063,-122.3492774")
    assert r.latlng == "47.6205063,-122.3492774"


def test_place_search_request() -> None:
    r = PlaceSearchRequest(query="coffee Seattle")
    assert r.query == "coffee Seattle"


def test_place_details_request_place_id() -> None:
    r = PlaceDetailsRequest(place_id="ChIJVTPokywQkFQRmtVEaUZlJRA")
    assert r.place_id == "ChIJVTPokywQkFQRmtVEaUZlJRA"


def test_directions_request() -> None:
    r = DirectionsRequest(
        origin="Space Needle Seattle WA",
        destination="Pike Place Market Seattle WA",
        travel_mode="bicycling",
        optimize_waypoints=True,
    )
    assert r.travel_mode == "bicycling"
    assert r.optimize_waypoints is True


def test_map_view_request() -> None:
    r = MapViewRequest(center="47.6062,-122.3321", zoom=12, basemap="satellite", layer="transit")
    assert r.basemap == "satellite"


def test_distance_matrix_request() -> None:
    r = DistanceMatrixRequest(
        origins=["Space Needle Seattle WA"],
        destinations=["Pike Place Market Seattle WA"],
        travel_mode="walking",
    )
    assert len(r.origins) == 1


@pytest.mark.parametrize(
    ("width", "height"),
    [(-1, 720), (0, 720), (MAX_VIEWPORT_DIMENSION + 1, 720), (3840, 2161)],
)
def test_viewport_rejects_unsafe_dimensions(width: int, height: int) -> None:
    with pytest.raises(ValidationError):
        ViewportSize(width=width, height=height)


def test_street_view_rejects_unsafe_image_dimensions() -> None:
    with pytest.raises(ValidationError, match="may not exceed"):
        StreetViewRequest(size=f"{MAX_STREET_VIEW_DIMENSION + 1}x360")


def test_requests_reject_oversized_text_and_combined_urls() -> None:
    with pytest.raises(ValidationError):
        GeocodeRequest(address="x" * (MAX_INPUT_LENGTH + 1))

    with pytest.raises(ValidationError, match="Maps URL exceeds"):
        DirectionsRequest(
            origin="o" * MAX_INPUT_LENGTH,
            destination="d" * MAX_INPUT_LENGTH,
            waypoints=["w" * MAX_INPUT_LENGTH] * 4,
        )


@pytest.mark.parametrize(
    ("origins", "destinations"),
    [([], ["B"]), (["A"], []), (["A"] * 5, ["B"] * 6)],
)
def test_distance_matrix_rejects_empty_or_excessive_workloads(
    origins: list[str], destinations: list[str]
) -> None:
    with pytest.raises(ValidationError):
        DistanceMatrixRequest(origins=origins, destinations=destinations)


def test_distance_matrix_accepts_the_element_limit() -> None:
    accepted = DistanceMatrixRequest(origins=["A"] * 5, destinations=["B"] * 5)
    assert len(accepted.origins) * len(accepted.destinations) == MAX_MATRIX_ELEMENTS


def test_elevation_request() -> None:
    r = ElevationRequest(locations=["Denver,CO"])
    assert r.locations == ["Denver,CO"]


def test_time_zone_request() -> None:
    r = TimeZoneRequest(location="47.6062,-122.3321", timestamp=1609459200)
    assert r.timestamp == 1609459200


def test_street_view_extracted_defaults() -> None:
    e = StreetViewExtracted()
    assert e.unsupported_api_fields == []
    assert e.screenshot is None


def test_geocode_extracted() -> None:
    e = GeocodeExtracted(
        input="Space Needle Seattle WA",
        input_type="address",
        coordinates=CoordinatePair(lat=47.6205, lng=-122.3493),
    )
    assert e.coordinates is not None
    assert e.coordinates.lat == 47.6205


def test_reverse_geocode_extracted() -> None:
    e = ReverseGeocodeExtracted(input_coordinates="47.6205063,-122.3492774")
    assert e.nearest_address_or_place is None


def test_place_extracted() -> None:
    e = PlaceExtracted(name="Space Needle", rating=4.7)
    assert e.rating == 4.7


def test_directions_extracted() -> None:
    e = DirectionsExtracted(origin="A", destination="B", travel_mode="driving")
    assert e.routes == []
    assert e.unsupported_api_fields == []


def test_map_view_extracted() -> None:
    e = MapViewExtracted(requested_center="47.6062,-122.3321")
    assert e.requested_zoom is None


def test_distance_matrix_extracted() -> None:
    from free_gmaps_api.contracts.extracted import DistanceMatrixElement

    elem = DistanceMatrixElement(status="ok", distance_text="2.3 mi", duration_text="12 min")
    e = DistanceMatrixExtracted(
        origins=["A"],
        destinations=["B"],
        elements=[[elem]],
    )
    assert e.elements[0][0].status == "ok"


def test_not_supported_extracted() -> None:
    e = NotSupportedExtracted(message="Elevation not supported.", endpoint="elevation")
    assert e.status == "not_supported"
