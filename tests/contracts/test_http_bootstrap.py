from __future__ import annotations

import pytest

from free_gmaps_api.http.bootstrap import BootstrapParseError, parse_maps_bootstrap
from free_gmaps_api.http.parsers import PayloadParseError, parse_xssi_json


def test_bootstrap_parses_server_json_without_javascript() -> None:
    bootstrap = parse_maps_bootstrap(
        '<script>window.APP_INITIALIZATION_STATE=["Space Needle", [47.6205, -122.3493]];'
        'window.APP_OPTIONS={"locale":"en-US"};</script>',
        "https://www.google.com/maps/search/?api=1",
    )
    assert bootstrap.initialization_state[0] == "Space Needle"
    assert bootstrap.app_options == {"locale": "en-US"}


@pytest.mark.parametrize(
    "html",
    ["", "window.APP_INITIALIZATION_STATE={};", "window.APP_INITIALIZATION_STATE=["],
)
def test_bootstrap_rejects_missing_or_invalid_state(html: str) -> None:
    with pytest.raises(BootstrapParseError):
        parse_maps_bootstrap(html, "https://www.google.com/maps/")


def test_xssi_parser_removes_only_the_expected_prefix() -> None:
    assert parse_xssi_json(')]}\'\n[["route"]]') == [["route"]]
    with pytest.raises(PayloadParseError):
        parse_xssi_json(")]}'not-json")
