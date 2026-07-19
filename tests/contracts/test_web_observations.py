from __future__ import annotations

import json
from pathlib import Path

import pytest

from free_gmaps_api.web.parsers import (
    parse_directions_routes,
    parse_primary_place_card,
    parse_search_place,
)

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "google_web" / "2026-07"


def test_structured_place_parser_anchors_identity_before_coordinates() -> None:
    payload = json.loads((_FIXTURES / "space_needle_search.json").read_text(encoding="utf-8"))

    place = parse_search_place(
        payload,
        query="Space Needle Seattle WA",
        expected_place_id="ChIJ-bfVTh8VkFQRDZLQnmioK9s",
    )

    assert place is not None
    assert place.name == "Space Needle"
    assert place.address == "400 Broad St, Seattle, WA 98109"
    assert place.official_place_id == "ChIJ-bfVTh8VkFQRDZLQnmioK9s"
    assert place.coordinates is not None
    assert place.coordinates.lat == pytest.approx(47.6205063)
    assert place.coordinates.lng == pytest.approx(-122.3492774)


def test_structured_place_parser_rejects_unanchored_plausible_values() -> None:
    payload = [["m", [51.7546255, 35.502669]], ["unrelated", [47.6205, -122.3492]]]

    assert parse_search_place(payload, query="Space Needle Seattle WA") is None


def test_structured_place_parser_rejects_identity_and_coordinates_in_sibling_records() -> None:
    payload = [["Space Needle"], [[47.6205063, -122.3492774]]]

    assert parse_search_place(payload, query="Space Needle Seattle WA") is None


def test_structured_place_parser_rejects_excessively_deep_payload() -> None:
    payload: object = "Space Needle"
    for _ in range(70):
        payload = [payload]

    assert parse_search_place(payload, query="Space Needle Seattle WA") is None


def test_primary_card_stops_before_nested_child_rating_and_filters_icons() -> None:
    text = (_FIXTURES / "space_needle_visible.txt").read_text(encoding="utf-8")

    place = parse_primary_place_card(text, query="Space Needle Seattle WA")

    assert place is not None
    assert place.name == "Space Needle"
    assert place.address == "400 Broad St, Seattle, WA 98109"
    assert place.category == "Observation deck"
    assert place.rating == 4.6
    assert place.review_count is None


def test_directions_parser_preserves_fixture_routes() -> None:
    payload = json.loads((_FIXTURES / "space_needle_directions.json").read_text(encoding="utf-8"))

    routes = parse_directions_routes(
        payload,
        origin="Space Needle Seattle WA",
        destination="Pike Place Market Seattle WA",
    )

    assert len(routes) == 2
    assert routes[0].duration_text == "12 min"
    assert routes[0].distance_text == "1.2 miles"
    assert routes[0].label == "via 2nd Ave"


def test_place_parser_does_not_take_coordinates_from_nested_foreign_record() -> None:
    payload = [
        "Space Needle",
        "400 Broad St, Seattle, WA 98109",
        ["Moscow", [55.7558, 37.6173]],
    ]

    place = parse_search_place(payload, query="Space Needle Seattle WA")

    assert place is not None
    assert place.name == "Space Needle"
    assert place.coordinates is None


def test_place_parser_does_not_take_coordinates_from_related_child_record() -> None:
    payload = [
        "Space Needle",
        "ChIJ-bfVTh8VkFQRDZLQnmioK9s",
        "400 Broad St, Seattle, WA 98109",
        ["Space Needle Lounge", [51.5, 35.5]],
    ]

    place = parse_search_place(
        payload,
        query="Space Needle Seattle WA",
        expected_place_id="ChIJ-bfVTh8VkFQRDZLQnmioK9s",
    )

    assert place is not None
    assert place.coordinates is None


def test_directions_parser_rejects_unanchored_route_labels() -> None:
    payload = [["12 min", "1.2 miles", "via 2nd Ave"]]

    assert (
        parse_directions_routes(
            payload,
            origin="Space Needle Seattle WA",
            destination="Pike Place Market Seattle WA",
        )
        == []
    )


def test_directions_parser_rejects_duration_and_distance_in_sibling_records() -> None:
    payload = [
        "Space Needle Seattle WA",
        "Pike Place Market Seattle WA",
        ["12 min"],
        ["1.2 miles"],
    ]

    assert (
        parse_directions_routes(
            payload,
            origin="Space Needle Seattle WA",
            destination="Pike Place Market Seattle WA",
        )
        == []
    )


def test_directions_parser_accepts_metrics_in_one_wrapped_route_record() -> None:
    payload = [
        [
            "Space Needle Seattle WA",
            "Pike Place Market Seattle WA",
            [[None, "2nd Ave"], [None, "1.2 miles"], [None, "10 min"]],
        ],
    ]

    routes = parse_directions_routes(
        payload,
        origin="Space Needle Seattle WA",
        destination="Pike Place Market Seattle WA",
    )

    assert len(routes) == 1
    assert routes[0].distance_text == "1.2 miles"
    assert routes[0].duration_text == "10 min"
    assert routes[0].label == "via 2nd Ave"


def test_directions_parser_rejects_unrelated_nested_route() -> None:
    payload = [
        [
            "Space Needle Seattle WA",
            "Pike Place Market Seattle WA",
            ["10 min", "1.2 miles", "via 2nd Ave"],
        ],
        ["recommendations", [["180 min", "100 miles", "via I-90"]]],
    ]

    routes = parse_directions_routes(
        payload,
        origin="Space Needle Seattle WA",
        destination="Pike Place Market Seattle WA",
    )

    assert len(routes) == 1
    assert routes[0].duration_text == "10 min"
