from __future__ import annotations

import pytest

from free_gmaps_api.services.directions import (
    _distance_meters,
    _duration_seconds,
    _parse_routes,
    _parse_steps,
)


@pytest.mark.parametrize(
    ("display", "seconds"),
    [
        ("8 min", 480),
        ("1 hr", 3600),
        ("1 hour 5 minutes", 3900),
    ],
)
def test_duration_display_normalization(display: str, seconds: int) -> None:
    assert _duration_seconds(display) == seconds


@pytest.mark.parametrize(
    ("display", "meters"),
    [
        ("253 ft", 77),
        ("1.2 miles", 1931),
        ("2.5 km", 2500),
        ("400 meters", 400),
    ],
)
def test_distance_display_normalization(display: str, meters: int) -> None:
    assert _distance_meters(display) == meters


def test_route_parser_groups_visible_cards_and_ignores_mode_summaries() -> None:
    routes = _parse_routes(
        "Best\n8 min\n13 min\n23 min\n"
        "8 min\n1.2 miles\nvia 2nd Ave\nFastest route now\n"
        "9 min\n1.3 miles\nvia 3rd Ave\nSome traffic, as usual"
    )

    assert len(routes) == 2
    assert routes[0].label == "via 2nd Ave"
    assert routes[0].summary == "Fastest route now"
    assert routes[1].duration_seconds_approximate == 540
    assert routes[1].distance_meters_approximate == 2092


def test_step_parser_stops_before_map_scale() -> None:
    steps = _parse_steps(
        "from A\n"
        "to B\n"
        "8 min (1.2 miles)\n"
        "via 2nd Ave\n"
        "Head north\n"
        "253 ft\n"
        "Turn right\n"
        "0.2 mi\n"
        "B\n"
        "Sign in\n"
        "Imagery 2026\n"
        "1000 ft"
    )

    assert [step.instruction for step in steps] == ["Head north", "Turn right"]
    assert [step.distance_meters_approximate for step in steps] == [77, 322]
