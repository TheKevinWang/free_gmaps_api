from __future__ import annotations

import json
from pathlib import Path

import pytest

from free_gmaps_api.browser.session import CapturedResponse
from free_gmaps_api.browser.street_view_image import CleanStreetViewImage
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


class FakeBrowserSession:
    def __init__(
        self,
        artifact_dir: str | None = None,
        interaction_error: str | None = None,
        captured_responses: list[CapturedResponse] | None = None,
        routes_after_interaction_only: bool = False,
        visible_override: str | None = None,
        current_url_override: str | None = None,
        screenshot_value: str | None = "artifacts/screenshot.png",
    ) -> None:
        self.urls: list[str] = []
        self.interaction_names: list[str | None] = []
        self.response_capture_names: list[tuple[str, ...]] = []
        self.artifact_dir = artifact_dir
        self.interaction_error = interaction_error
        self.captured_responses = captured_responses or []
        self.routes_after_interaction_only = routes_after_interaction_only
        self.visible_override = visible_override
        self.current_url_override = current_url_override
        self.screenshot_value = screenshot_value

    async def navigate(
        self,
        url: str,
        request_id: str | None = None,
        viewport: tuple[int, int] | None = None,
        interaction: object | None = None,
        interaction_name: str | None = None,
        response_captures: tuple[object, ...] = (),
    ) -> dict[str, object]:
        del request_id, viewport
        self.urls.append(url)
        self.interaction_names.append(interaction_name)
        self.response_capture_names.append(
            tuple(str(getattr(capture, "name", "")) for capture in response_captures)
        )
        if "/dir/" in url:
            visible_text = (
                ""
                if self.routes_after_interaction_only
                else (
                    "12 min\n1.0 mile\nvia 2nd Ave\nFastest route now\n"
                    "14 min\n1.4 miles\nvia 1st Ave\nUse caution on this route"
                )
            )
            current_url = url
        elif "query=47.6205063" in url:
            visible_text = "47°37′13.8″N, 122°20′57.4″W\n47.6205063, -122.3492774\n84VV+XW Seattle"
            current_url = url
        else:
            visible_text = (
                "Space Needle\nObservation deck\n4.7 (20,000)\n"
                "400 Broad St, Seattle, WA\n84VV+XW Seattle"
            )
            current_url = (
                "https://www.google.com/maps/place/Space+Needle/@47.6205063,-122.3492774,17z"
            )
        if self.visible_override is not None:
            visible_text = self.visible_override
        if self.current_url_override is not None:
            current_url = self.current_url_override
        result: dict[str, object] = {
            "current_url": current_url,
            "candidate_maps_urls": [current_url],
            "screenshot": self.screenshot_value,
            "raw_visible_text": visible_text,
            "visible_text_path": "artifacts/visible-text.txt",
            "accessibility_path": "artifacts/accessibility.json",
            "trace_path": "artifacts/trace.zip",
            "response_path": "artifacts/response.json",
            "captured_responses": self.captured_responses,
        }
        if "/dir/" in url and interaction is not None:
            if self.interaction_error is not None:
                result["interaction_error"] = self.interaction_error
            else:
                result["interaction_visible_text"] = (
                    "from Space Needle, 400 Broad St, Seattle, WA 98109\n"
                    "to Pike Place Market, Seattle, WA\n"
                    "12 min (1.0 mile)\n"
                    "via 2nd Ave\n"
                    "Fastest route now\n"
                    "Space Needle\n"
                    "400 Broad St, Seattle, WA 98109\n"
                    "Head toward Space Needle Loop\n"
                    "253 ft\n"
                    "Turn right onto Broad St\n"
                    "0.8 mi\n"
                    "Pike Place Market\n"
                    "Seattle, WA\n"
                    "Sign in\n"
                    "1000 ft"
                )
                result["interaction_screenshot"] = "artifacts/interaction-screenshot.png"
                result["interaction_visible_text_path"] = "artifacts/interaction-visible-text.txt"
                result["interaction_accessibility_path"] = (
                    "artifacts/interaction-accessibility.json"
                )
        if self.artifact_dir is not None:
            result["artifact_dir"] = self.artifact_dir
        return result


async def test_directions_service_parses_visible_route() -> None:
    session = FakeBrowserSession()
    response = await run_directions(
        DirectionsRequest(origin="Space Needle", destination="Pike Place Market"),
        session,  # type: ignore[arg-type]
    )
    assert response.ok is True
    assert response.extracted.selected_route is not None
    assert response.extracted.selected_route.duration_text == "12 min"
    assert response.extracted.selected_route.distance_text == "1.0 mile"
    assert response.extracted.selected_route.duration_seconds_approximate == 720
    assert response.extracted.selected_route.distance_meters_approximate == 1609
    assert response.extracted.selected_route.label == "via 2nd Ave"
    assert len(response.extracted.selected_route.steps) == 2
    assert response.extracted.selected_route.steps[0].instruction == (
        "Head toward Space Needle Loop"
    )
    assert response.extracted.selected_route.steps[0].distance_meters_approximate == 77
    assert response.extracted.resolved_origin == ("Space Needle, 400 Broad St, Seattle, WA 98109")
    assert response.extracted.resolved_destination == "Pike Place Market, Seattle, WA"
    assert len(response.extracted.routes) == 1
    assert response.confidence.overall == "high"
    assert response.artifacts.trace == "artifacts/trace.zip"
    assert response.artifacts.interaction_visible_text == ("artifacts/interaction-visible-text.txt")


async def test_directions_service_returns_visible_alternatives_when_requested() -> None:
    session = FakeBrowserSession()
    response = await run_directions(
        DirectionsRequest(
            origin="Space Needle",
            destination="Pike Place Market",
            alternatives=True,
        ),
        session,  # type: ignore[arg-type]
    )

    assert response.ok is True
    assert len(response.extracted.routes) == 2
    assert response.extracted.routes[0].label == "via 2nd Ave"
    assert response.extracted.routes[1].label == "via 1st Ave"
    assert response.extracted.routes[1].summary == "Use caution on this route"
    assert response.extracted.routes[1].distance_meters_approximate == 2253
    assert response.extracted.warnings == ["Use caution on this route"]


async def test_directions_service_preserves_routes_when_details_fail() -> None:
    session = FakeBrowserSession(interaction_error="Details button unavailable")
    response = await run_directions(
        DirectionsRequest(origin="Space Needle", destination="Pike Place Market"),
        session,  # type: ignore[arg-type]
    )

    assert response.ok is True
    assert response.extracted.selected_route is not None
    assert response.extracted.selected_route.steps == []
    assert response.confidence.overall == "medium"
    assert response.confidence.notes == [
        "Directions Details interaction failed: Details button unavailable"
    ]


async def test_directions_service_uses_route_cards_that_render_after_interaction() -> None:
    session = FakeBrowserSession(routes_after_interaction_only=True)

    response = await run_directions(
        DirectionsRequest(origin="Space Needle", destination="Pike Place Market"),
        session,  # type: ignore[arg-type]
    )

    assert response.ok is True
    assert response.extracted.selected_route is not None
    assert response.extracted.selected_route.duration_text == "12 min"
    assert response.extracted.selected_route.distance_text == "1.0 mile"


async def test_geocode_and_reverse_geocode_services() -> None:
    session = FakeBrowserSession()
    geocode = await run_geocode(
        GeocodeRequest(address="Space Needle Seattle WA"),
        session,  # type: ignore[arg-type]
    )
    reverse = await run_reverse_geocode(
        ReverseGeocodeRequest(latlng="47.6205063,-122.3492774"),
        session,  # type: ignore[arg-type]
    )
    assert geocode.ok is True
    assert geocode.extracted.coordinates is not None
    assert reverse.ok is False
    assert reverse.extracted.display_coordinates_decimal == "47.6205063, -122.3492774"
    assert reverse.extracted.nearest_address_or_place is None


async def test_reverse_geocode_requires_coordinate_tied_address_evidence() -> None:
    payload = [
        [
            "Space Needle",
            "400 Broad St, Seattle, WA 98109",
            [47.6205063, -122.3492774],
            "ChIJ-bfVTh8VkFQRDZLQnmioK9s",
        ]
    ]
    session = FakeBrowserSession(
        captured_responses=[
            CapturedResponse(
                name="maps-search",
                url_path="/search",
                status=200,
                content_type="application/json",
                body=json.dumps(payload).encode(),
            )
        ]
    )

    reverse = await run_reverse_geocode(
        ReverseGeocodeRequest(latlng="47.6205063,-122.3492774"),
        session,  # type: ignore[arg-type]
    )

    assert reverse.ok is True
    assert reverse.extracted.nearest_address_or_place == "400 Broad St, Seattle, WA 98109"


async def test_geocode_uses_identity_anchored_capture_when_address_bar_stays_search() -> None:
    payload = [
        ["unrelated", [51.7546255, 35.502669]],
        [
            "Space Needle",
            "400 Broad St, Seattle, WA 98109",
            [47.6205063, -122.3492774],
            "ChIJ-bfVTh8VkFQRDZLQnmioK9s",
        ],
    ]
    session = FakeBrowserSession(
        captured_responses=[
            CapturedResponse(
                name="maps-search",
                url_path="/search",
                status=200,
                content_type="application/json",
                body=json.dumps(payload).encode(),
            )
        ]
    )

    response = await run_geocode(
        GeocodeRequest(address="Space Needle Seattle WA"),
        session,  # type: ignore[arg-type]
    )

    assert response.ok is True
    assert response.extracted.display_name == "Space Needle"
    assert response.extracted.coordinates is not None
    assert response.extracted.coordinates.lat == pytest.approx(47.6205063)


async def test_geocode_rejects_unrelated_visible_fallback_despite_coordinate_url() -> None:
    session = FakeBrowserSession(
        visible_override="Before you continue to Google\nAccept all",
        current_url_override=(
            "https://www.google.com/maps/place/Unrelated/@47.6205063,-122.3492774,17z"
        ),
    )

    response = await run_geocode(
        GeocodeRequest(address="Space Needle Seattle WA"),
        session,  # type: ignore[arg-type]
    )

    assert response.ok is False
    assert response.extracted.coordinates is None
    assert response.extracted.display_name is None


async def test_geocode_with_place_id_rejects_matching_visible_query_without_id_evidence() -> None:
    session = FakeBrowserSession()

    response = await run_geocode(
        GeocodeRequest(
            address="Space Needle Seattle WA",
            place_id="ChIJ-bfVTh8VkFQRDZLQnmioK9s",
        ),
        session,  # type: ignore[arg-type]
    )

    assert response.ok is False
    assert response.extracted.coordinates is None
    assert response.extracted.display_name is None


async def test_place_details_with_official_id_requires_same_id_evidence() -> None:
    session = FakeBrowserSession()

    response = await run_place_details(
        PlaceDetailsRequest(place_id="ChIJ-bfVTh8VkFQRDZLQnmioK9s"),
        session,  # type: ignore[arg-type]
    )

    assert response.ok is False
    assert response.extracted.coordinates is None


async def test_place_details_query_and_id_require_exact_structured_id() -> None:
    session = FakeBrowserSession()

    response = await run_place_details(
        PlaceDetailsRequest(
            query="Space Needle Seattle WA",
            place_id="ChIJ-bfVTh8VkFQRDZLQnmioK9s",
        ),
        session,  # type: ignore[arg-type]
    )

    assert response.ok is False
    assert response.extracted.coordinates is None


@pytest.mark.parametrize("capture_name", ["maps-search", "maps-place"])
async def test_place_details_query_and_id_accept_exact_structured_id(
    capture_name: str,
) -> None:
    payload = [
        [
            "Space Needle",
            "400 Broad St, Seattle, WA 98109",
            [47.6205063, -122.3492774],
            "ChIJ-bfVTh8VkFQRDZLQnmioK9s",
        ]
    ]
    session = FakeBrowserSession(
        captured_responses=[
            CapturedResponse(
                name=capture_name,
                url_path="/search" if capture_name == "maps-search" else "/maps/preview/place",
                status=200,
                content_type="application/json",
                body=json.dumps(payload).encode(),
            )
        ]
    )

    response = await run_place_details(
        PlaceDetailsRequest(
            query="Space Needle Seattle WA",
            place_id="ChIJ-bfVTh8VkFQRDZLQnmioK9s",
        ),
        session,  # type: ignore[arg-type]
    )

    assert response.ok is True
    assert response.extracted.official_place_id == "ChIJ-bfVTh8VkFQRDZLQnmioK9s"
    assert response.extracted.coordinates is not None
    assert session.response_capture_names == [("maps-search", "maps-place")]


async def test_place_details_preview_capture_rejects_sibling_official_id() -> None:
    payload = [
        [
            "Space Needle",
            "400 Broad St, Seattle, WA 98109",
            [47.6205063, -122.3492774],
            "ChIJSiblingPlaceId00000000",
        ]
    ]
    session = FakeBrowserSession(
        captured_responses=[
            CapturedResponse(
                name="maps-place",
                url_path="/maps/preview/place",
                status=200,
                content_type="application/json",
                body=json.dumps(payload).encode(),
            )
        ]
    )

    response = await run_place_details(
        PlaceDetailsRequest(
            query="Space Needle Seattle WA",
            place_id="ChIJ-bfVTh8VkFQRDZLQnmioK9s",
        ),
        session,  # type: ignore[arg-type]
    )

    assert response.ok is False
    assert response.extracted.official_place_id is None
    assert response.extracted.coordinates is None


@pytest.mark.parametrize(
    "maps_url",
    [
        "https://example.com/maps/place/Space+Needle",
        "http://127.0.0.1/maps/place/Space+Needle",
        "file:///etc/passwd",
    ],
)
async def test_place_details_rejects_noncanonical_maps_url(maps_url: str) -> None:
    session = FakeBrowserSession()

    response = await run_place_details(
        PlaceDetailsRequest(maps_url=maps_url),
        session,  # type: ignore[arg-type]
    )

    assert response.ok is False
    assert session.urls == []


async def test_place_search_and_details_services() -> None:
    session = FakeBrowserSession()
    search = await run_place_search(
        PlaceSearchRequest(query="Space Needle Seattle WA"),
        session,  # type: ignore[arg-type]
    )
    details = await run_place_details(
        PlaceDetailsRequest(query="Space Needle Seattle WA"),
        session,  # type: ignore[arg-type]
    )
    assert search.ok is True
    assert search.extracted.name == "Space Needle"
    assert details.ok is True
    assert details.extracted.coordinates is not None


async def test_street_view_and_map_view_apply_browser_artifacts() -> None:
    session = FakeBrowserSession()
    street_view = await run_street_view(
        StreetViewRequest(location="47.6205063,-122.3492774"),
        session,  # type: ignore[arg-type]
    )
    map_view = await run_map_view(
        MapViewRequest(center="47.6205063,-122.3492774", zoom=17),
        session,  # type: ignore[arg-type]
    )
    assert street_view.ok is True
    assert street_view.extracted.image is not None
    assert street_view.extracted.image.clean is False
    assert street_view.extracted.image.source == "browser_screenshot"
    assert street_view.extracted.screenshot is not None
    assert street_view.artifacts.accessibility == "artifacts/accessibility.json"
    assert map_view.ok is True
    assert map_view.extracted.resolved_center is not None


async def test_street_view_prefers_clean_renderer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake_download(*args: object, **kwargs: object) -> CleanStreetViewImage:
        del args, kwargs
        image_path = tmp_path / "street-view.jpg"
        image_path.write_bytes(b"jpeg")
        return CleanStreetViewImage(
            path=str(image_path),
            width=640,
            height=360,
            content_type="image/jpeg",
            renderer_url="https://lh3.googleusercontent.com/example=w640-h360-fo80",
        )

    monkeypatch.setattr(
        "free_gmaps_api.services.street_view.download_clean_street_view_image",
        fake_download,
    )
    session = FakeBrowserSession(artifact_dir=str(tmp_path))
    response = await run_street_view(
        StreetViewRequest(location="47.6205063,-122.3492774", size="640x360", fov=80.0),
        session,  # type: ignore[arg-type]
    )

    assert response.ok is True
    assert response.extracted.image is not None
    assert response.extracted.image.clean is True
    assert response.extracted.image.source == "web_renderer"
    assert response.extracted.image.width == 640
    assert response.artifacts.street_view_image == response.extracted.image.path


async def test_street_view_fails_without_clean_image_or_optional_screenshot() -> None:
    session = FakeBrowserSession(screenshot_value=None)

    response = await run_street_view(
        StreetViewRequest(location="47.6205063,-122.3492774"),
        session,  # type: ignore[arg-type]
    )

    assert response.ok is False
    assert response.extracted.image is None
    assert response.extracted.screenshot is None
    assert response.artifacts.screenshot is None
    assert "No fallback UI screenshot" in response.confidence.notes[-1]


async def test_distance_matrix_preserves_shape() -> None:
    session = FakeBrowserSession()
    response = await run_distance_matrix(
        DistanceMatrixRequest(
            origins=["Space Needle", "Seattle Center"],
            destinations=["Pike Place Market"],
        ),
        session,  # type: ignore[arg-type]
    )
    assert response.ok is True
    assert len(response.extracted.elements) == 2
    assert len(response.extracted.elements[0]) == 1
    assert response.extracted.elements[0][0].status == "ok"
    assert session.interaction_names == [
        "open-directions-details",
        "open-directions-details",
    ]


async def test_browser_matrix_defensively_rejects_bypassed_empty_axis() -> None:
    session = FakeBrowserSession()
    invalid = DistanceMatrixRequest.model_construct(origins=["A"], destinations=[])

    response = await run_distance_matrix(invalid, session)  # type: ignore[arg-type]

    assert response.ok is False
    assert response.extracted.elements == [[]]
    assert session.urls == []


async def test_distance_matrix_uses_bounded_details_when_initial_route_is_empty() -> None:
    session = FakeBrowserSession(routes_after_interaction_only=True)

    response = await run_distance_matrix(
        DistanceMatrixRequest(
            origins=["Space Needle"],
            destinations=["Pike Place Market"],
        ),
        session,  # type: ignore[arg-type]
    )

    assert response.ok is True
    assert len(response.extracted.elements) == 1
    assert len(response.extracted.elements[0]) == 1
    element = response.extracted.elements[0][0]
    assert element.status == "ok"
    assert element.distance_text == "1.0 mile"
    assert element.duration_text == "12 min"
    assert session.interaction_names == ["open-directions-details"]
