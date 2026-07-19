from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel

from free_gmaps_api.browser.artifacts import make_artifact_dir
from free_gmaps_api.browser.extract import (
    extract_coordinates_from_url,
    extract_orientation_from_url,
    extract_place_url_ids,
    extract_zoom_from_url,
)
from free_gmaps_api.browser.street_view_image import (
    build_renderer_url,
    renderer_url_from_metadata,
)
from free_gmaps_api.contracts.envelope import ApiEnvelope, ArtifactSet, Confidence
from free_gmaps_api.contracts.extracted import (
    CoordinatePair,
    DirectionsExtracted,
    DirectionsRoute,
    DistanceMatrixElement,
    DistanceMatrixExtracted,
    GeocodeExtracted,
    LocationResolution,
    MapViewExtracted,
    PlaceExtracted,
    ReverseGeocodeExtracted,
    StreetViewExtracted,
    StreetViewImage,
    StreetViewOrientation,
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
from free_gmaps_api.http.bootstrap import BootstrapParseError, MapsBootstrap, parse_maps_bootstrap
from free_gmaps_api.http.client import HttpAdapterError, HttpExchange, MapsHttpClient
from free_gmaps_api.http.images import image_dimensions
from free_gmaps_api.http.parsers import (
    PayloadParseError,
    first_coordinate,
    parse_xssi_json,
    strings_in,
)
from free_gmaps_api.http.payloads import (
    build_directions_preview_params,
    build_place_photo_batch_request,
    build_street_view_metadata_params,
)
from free_gmaps_api.http.street_view import (
    PlaceStreetViewPanorama,
    PlaceStreetViewParseError,
    exact_panorama_renderer_url,
    parse_place_street_view_response,
    place_identity_from_url,
)
from free_gmaps_api.maps_urls.directions import build_directions_url
from free_gmaps_api.maps_urls.map_view import build_map_view_url
from free_gmaps_api.maps_urls.search import build_search_url
from free_gmaps_api.maps_urls.security import validate_google_maps_url
from free_gmaps_api.maps_urls.street_view import build_street_view_url
from free_gmaps_api.settings import Settings
from free_gmaps_api.support.matrix import get_unsupported_fields
from free_gmaps_api.web.observations import ObservedCoordinates, ObservedPlace
from free_gmaps_api.web.parsers import parse_directions_routes, parse_search_place

T = TypeVar("T", bound=BaseModel)
_RENDERER_URL = re.compile(
    r"https://(?:lh\d+\.googleusercontent\.com|streetviewpixels-pa\.googleapis\.com)/[^\"'\\ ]+"
)


class HttpBackend:
    """HTTP-only implementation of the public Maps contract.

    Maps HTML is used as the stable bootstrap transport.  The adapter returns a
    low-confidence envelope when Google changes a layout instead of starting a
    browser or guessing at undocumented array positions.
    """

    @property
    def name(self) -> Literal["http"]:
        return "http"

    def __init__(self, settings: Settings, *, client: MapsHttpClient | None = None) -> None:
        self._settings = settings
        self._client = client or MapsHttpClient(settings)

    async def close(self) -> None:
        await self._client.close()

    async def geocode(self, request: GeocodeRequest) -> ApiEnvelope[GeocodeExtracted]:
        unsupported = get_unsupported_fields("geocode", request)
        query = request.address or (f"place_id:{request.place_id}" if request.place_id else None)
        if not query:
            return self._error(
                request,
                None,
                GeocodeExtracted(unsupported_api_fields=unsupported),
                "Must provide 'address' or 'place_id'.",
            )
        url = build_search_url(query, request.place_id)
        try:
            _, _, artifacts = await self._bootstrap(url, "geocode")
            observation = await self._search_place(
                query,
                referer=url,
                expected_place_id=request.place_id,
            )
            coords = _observed_coordinates(observation)
            ok = observation is not None and bool(
                coords or (observation.name and observation.address)
            )
            return ApiEnvelope(
                ok=ok,
                source="google_maps_web",
                request=request.model_dump(),
                maps_url=url,
                extracted=GeocodeExtracted(
                    input=query,
                    input_type="address" if request.address else "place_id",
                    formatted_address=observation.address if observation else None,
                    display_name=observation.name if observation else None,
                    coordinates=coords,
                    place_url=observation.canonical_url if observation else None,
                    unsupported_api_fields=unsupported,
                ),
                artifacts=artifacts,
                confidence=Confidence(
                    overall="medium" if ok else "low",
                    notes=[]
                    if ok
                    else ["No query-anchored place record was present in the Maps response."],
                ),
            )
        except (HttpAdapterError, BootstrapParseError) as exc:
            return self._error(
                request,
                url,
                GeocodeExtracted(input=query, unsupported_api_fields=unsupported),
                str(exc),
            )

    async def reverse_geocode(
        self, request: ReverseGeocodeRequest
    ) -> ApiEnvelope[ReverseGeocodeExtracted]:
        unsupported = get_unsupported_fields("reverse-geocode", request)
        url = build_search_url(request.latlng)
        try:
            _, _, artifacts = await self._bootstrap(url, "reverse-geocode")
            expected = _parse_coordinate(request.latlng)
            observation = await self._search_place(
                request.latlng,
                referer=url,
                expected_coordinates=(
                    ObservedCoordinates(expected.lat, expected.lng) if expected else None
                ),
            )
            ok = observation is not None and observation.address is not None
            return ApiEnvelope(
                ok=ok,
                source="google_maps_web",
                request=request.model_dump(),
                maps_url=url,
                extracted=ReverseGeocodeExtracted(
                    input_coordinates=request.latlng,
                    display_coordinates_decimal=request.latlng if ok else None,
                    nearest_address_or_place=(observation.address if observation else None),
                    place_url=observation.canonical_url if observation else None,
                    unsupported_api_fields=unsupported,
                ),
                artifacts=artifacts,
                confidence=Confidence(
                    overall="medium" if ok else "low",
                    notes=[]
                    if ok
                    else ["No address-bearing place record matched the requested coordinates."],
                ),
            )
        except (HttpAdapterError, BootstrapParseError) as exc:
            return self._error(
                request,
                url,
                ReverseGeocodeExtracted(
                    input_coordinates=request.latlng, unsupported_api_fields=unsupported
                ),
                str(exc),
            )

    async def place_search(self, request: PlaceSearchRequest) -> ApiEnvelope[PlaceExtracted]:
        return await self._place(
            request, request.query, build_search_url(request.query), "place-search"
        )

    async def place_details(self, request: PlaceDetailsRequest) -> ApiEnvelope[PlaceExtracted]:
        unsupported = get_unsupported_fields("place-details", request)
        if request.maps_url:
            try:
                url = validate_google_maps_url(request.maps_url)
            except ValueError as exc:
                return self._error(
                    request,
                    None,
                    PlaceExtracted(unsupported_api_fields=unsupported),
                    str(exc),
                )
            query = request.query or request.place_id or request.maps_url
        elif request.place_id and not request.query:
            return self._error(
                request,
                None,
                PlaceExtracted(unsupported_api_fields=unsupported),
                "HTTP place details requires a human query hint with place_id; "
                "Maps web cannot resolve an official ID alone.",
            )
        elif request.query:
            query = request.query
            url = build_search_url(query, request.place_id)
        else:
            return self._error(
                request,
                None,
                PlaceExtracted(unsupported_api_fields=unsupported),
                "Must provide place_id, maps_url, or query.",
            )
        return await self._place(request, query, url, "place-details")

    async def _place(
        self,
        request: PlaceSearchRequest | PlaceDetailsRequest,
        query: str | None,
        url: str,
        endpoint: Literal["place-search", "place-details"],
    ) -> ApiEnvelope[PlaceExtracted]:
        unsupported = get_unsupported_fields(endpoint, request)
        try:
            _, _, artifacts = await self._bootstrap(url, endpoint)
            expected_place_id = getattr(request, "place_id", None)
            observation = await self._search_place(
                query or url,
                referer=url,
                expected_place_id=expected_place_id,
            )
            coords = _observed_coordinates(observation)
            ids = (
                extract_place_url_ids(observation.canonical_url)
                if observation and observation.canonical_url
                else []
            )
            ok = observation is not None and bool(observation.name or observation.address or coords)
            return ApiEnvelope(
                ok=ok,
                source="google_maps_web",
                request=request.model_dump(),
                maps_url=url,
                extracted=PlaceExtracted(
                    query=query,
                    name=observation.name if observation else None,
                    category=observation.category if observation else None,
                    rating=observation.rating if observation else None,
                    review_count=observation.review_count if observation else None,
                    address=observation.address if observation else None,
                    place_detail_url=observation.canonical_url if observation else None,
                    coordinates=coords,
                    official_place_id=(observation.official_place_id if observation else None),
                    observed_maps_url_ids=ids,
                    id_provenance=(
                        "caller_supplied_official_place_id"
                        if expected_place_id
                        and observation
                        and observation.official_place_id == expected_place_id
                        else ("url_token" if ids else None)
                    ),
                    unsupported_api_fields=unsupported,
                ),
                artifacts=artifacts,
                confidence=Confidence(
                    overall="medium" if ok else "low",
                    notes=[]
                    if ok
                    else ["No query-anchored place record was present in the Maps response."],
                ),
            )
        except (HttpAdapterError, BootstrapParseError) as exc:
            return self._error(
                request,
                url,
                PlaceExtracted(query=query, unsupported_api_fields=unsupported),
                str(exc),
            )

    async def _search_place(
        self,
        query: str,
        *,
        referer: str,
        expected_place_id: str | None = None,
        expected_coordinates: ObservedCoordinates | None = None,
    ) -> ObservedPlace | None:
        exchange = await self._client.get_path(
            "https://www.google.com/search",
            endpoint="maps-search",
            params={
                "tbm": "map",
                "q": query,
                "hl": self._settings.locale,
            },
            referer=referer,
        )
        if "json" not in exchange.content_type:
            raise HttpAdapterError(
                "maps-search returned a non-JSON response; consent or layout drift is likely."
            )
        try:
            payload = parse_xssi_json(exchange.body.decode("utf-8"))
        except (UnicodeDecodeError, PayloadParseError) as exc:
            raise HttpAdapterError("maps-search returned malformed JSON.") from exc
        return parse_search_place(
            payload,
            query=query,
            expected_place_id=expected_place_id,
            expected_coordinates=expected_coordinates,
        )

    async def directions(self, request: DirectionsRequest) -> ApiEnvelope[DirectionsExtracted]:
        unsupported = get_unsupported_fields("directions", request)
        url = build_directions_url(
            request.origin,
            request.destination,
            request.travel_mode,
            request.waypoints or None,
            request.avoid or None,
        )
        try:
            _, bootstrap, artifacts = await self._bootstrap(url, "directions")
            exchange = await self._client.get_path(
                "https://www.google.com/maps/preview/directions",
                endpoint="directions-preview",
                params=build_directions_preview_params(
                    request, bootstrap, self._settings.locale, None
                ),
                referer=url,
            )
            if "json" not in exchange.content_type:
                raise HttpAdapterError(
                    "directions-preview returned a non-JSON response; consent or layout drift "
                    "is likely."
                )
            try:
                payload = parse_xssi_json(exchange.body.decode("utf-8"))
            except (UnicodeDecodeError, PayloadParseError) as exc:
                raise HttpAdapterError("directions-preview returned malformed JSON.") from exc
            parsed_routes = parse_directions_routes(
                payload,
                origin=request.origin,
                destination=request.destination,
            )
            parsed_routes = parsed_routes if request.alternatives else parsed_routes[:1]
            routes = [
                DirectionsRoute(
                    duration_text=route.duration_text,
                    distance_text=route.distance_text,
                    duration_seconds_approximate=_duration_seconds(route.duration_text),
                    distance_meters_approximate=_distance_meters(route.distance_text),
                    label=route.label,
                    summary=route.summary,
                )
                for route in parsed_routes
            ]
            selected = routes[0] if routes else None
            return ApiEnvelope(
                ok=bool(routes),
                source="google_maps_web",
                request=request.model_dump(),
                maps_url=url,
                extracted=DirectionsExtracted(
                    origin=request.origin,
                    destination=request.destination,
                    travel_mode=request.travel_mode,
                    routes=routes,
                    selected_route=selected,
                    unsupported_api_fields=unsupported,
                ),
                artifacts=artifacts,
                confidence=Confidence(
                    overall="medium" if routes else "low",
                    notes=[] if routes else ["No route summary appeared in the HTTP bootstrap."],
                ),
            )
        except (HttpAdapterError, BootstrapParseError) as exc:
            return self._error(
                request,
                url,
                DirectionsExtracted(
                    origin=request.origin,
                    destination=request.destination,
                    travel_mode=request.travel_mode,
                    unsupported_api_fields=unsupported,
                ),
                str(exc),
            )

    async def distance_matrix(
        self, request: DistanceMatrixRequest
    ) -> ApiEnvelope[DistanceMatrixExtracted]:
        unsupported = get_unsupported_fields("distance-matrix", request)
        rows: list[list[DistanceMatrixElement]] = []
        any_ok = False
        for origin in request.origins:
            row: list[DistanceMatrixElement] = []
            for destination in request.destinations:
                result = await self.directions(
                    DirectionsRequest(
                        origin=origin,
                        destination=destination,
                        travel_mode=request.travel_mode,
                        avoid=request.avoid,
                    )
                )
                selected = result.extracted.selected_route
                if result.ok and selected:
                    any_ok = True
                    row.append(
                        DistanceMatrixElement(
                            status="ok",
                            distance_text=selected.distance_text,
                            duration_text=selected.duration_text,
                            route_summary=selected.label or selected.summary,
                            travel_mode=request.travel_mode,
                            maps_url=result.maps_url,
                            confidence_notes=result.confidence.notes,
                        )
                    )
                else:
                    row.append(
                        DistanceMatrixElement(
                            status=_matrix_failure_status(result.confidence.notes),
                            travel_mode=request.travel_mode,
                            maps_url=result.maps_url,
                            confidence_notes=result.confidence.notes,
                        )
                    )
            rows.append(row)
        all_failed = not any_ok
        return ApiEnvelope(
            ok=not all_failed,
            source="google_maps_web",
            request=request.model_dump(),
            maps_url=None,
            extracted=DistanceMatrixExtracted(
                origins=request.origins,
                destinations=request.destinations,
                elements=rows,
                unsupported_api_fields=unsupported,
            ),
            artifacts=ArtifactSet(),
            confidence=Confidence(
                overall="low" if all_failed else "medium",
                notes=["All matrix element lookups failed."] if all_failed else [],
            ),
        )

    async def map_view(self, request: MapViewRequest) -> ApiEnvelope[MapViewExtracted]:
        unsupported = get_unsupported_fields("map-view", request)
        url = build_map_view_url(request.center, request.zoom, request.basemap, request.layer)
        try:
            exchange, bootstrap, artifacts = await self._bootstrap(url, "map-view")
            return ApiEnvelope(
                ok=True,
                source="google_maps_web",
                request=request.model_dump(),
                maps_url=url,
                extracted=MapViewExtracted(
                    requested_center=request.center,
                    requested_zoom=request.zoom,
                    requested_basemap=request.basemap,
                    requested_layer=request.layer,
                    resolved_url=exchange.final_url,
                    resolved_center=_coordinates(exchange.final_url, bootstrap),
                    resolved_zoom=extract_zoom_from_url(exchange.final_url) or float(request.zoom)
                    if request.zoom is not None
                    else None,
                    unsupported_api_fields=unsupported,
                ),
                artifacts=artifacts,
                confidence=Confidence(
                    overall="medium",
                    notes=[
                        "Raw HTTP does not render a Maps viewport, screenshot, or "
                        "accessibility tree."
                    ],
                ),
            )
        except (HttpAdapterError, BootstrapParseError) as exc:
            return self._error(
                request,
                url,
                MapViewExtracted(
                    requested_center=request.center,
                    requested_zoom=request.zoom,
                    requested_basemap=request.basemap,
                    requested_layer=request.layer,
                    unsupported_api_fields=unsupported,
                ),
                str(exc),
            )

    async def street_view(self, request: StreetViewRequest) -> ApiEnvelope[StreetViewExtracted]:
        unsupported = get_unsupported_fields("street-view", request)
        viewpoint = _parse_coordinate(request.location) if request.location else None
        location_resolution = LocationResolution(
            display_text=request.location,
            coordinates=viewpoint,
            source="caller_input" if viewpoint is not None else None,
        )
        selected_panorama: PlaceStreetViewPanorama | None = None
        selected_pano = request.pano
        selected_renderer: str | None = None
        if request.pano is not None:
            try:
                selected_renderer = exact_panorama_renderer_url(request.pano)
            except ValueError as exc:
                return self._error(
                    request,
                    None,
                    StreetViewExtracted(
                        requested_location=request.location,
                        requested_pano=request.pano,
                        unsupported_api_fields=unsupported,
                    ),
                    str(exc),
                )

        if selected_pano is None and viewpoint is None:
            if not request.location:
                return self._error(
                    request,
                    None,
                    StreetViewExtracted(
                        requested_location=request.location,
                        requested_pano=request.pano,
                        unsupported_api_fields=unsupported,
                    ),
                    "HTTP Street View requires an address, coordinates, or panorama ID.",
                )
            resolved = await self.geocode(GeocodeRequest(address=request.location))
            viewpoint = resolved.extracted.coordinates
            place_url = resolved.extracted.place_url
            if viewpoint is None or place_url is None:
                return self._error(
                    request,
                    resolved.maps_url,
                    StreetViewExtracted(
                        requested_location=request.location,
                        requested_pano=request.pano,
                        unsupported_api_fields=unsupported,
                    ),
                    "HTTP geocoding could not resolve the Street View address to an exact "
                    "Maps place.",
                )
            identity = place_identity_from_url(place_url)
            if identity is None:
                return self._error(
                    request,
                    resolved.maps_url,
                    StreetViewExtracted(
                        requested_location=request.location,
                        requested_pano=request.pano,
                        requested_viewpoint=viewpoint,
                        unsupported_api_fields=unsupported,
                    ),
                    "Resolved Maps place URL did not expose the identity required for its "
                    "Street View preview.",
                )
            batch = build_place_photo_batch_request(identity, self._settings.locale)
            try:
                photo_exchange = await self._client.post_form(
                    "https://www.google.com/maps/_/MapsWizUi/data/batchexecute",
                    endpoint="place-street-view-photos",
                    params=batch.params,
                    data=batch.data,
                    referer=identity.canonical_url,
                )
                if "json" not in photo_exchange.content_type.lower():
                    raise HttpAdapterError("Maps place-photo service returned a non-JSON response.")
                selected_panorama = parse_place_street_view_response(photo_exchange.body)
            except (HttpAdapterError, PlaceStreetViewParseError) as exc:
                return self._error(
                    request,
                    resolved.maps_url,
                    StreetViewExtracted(
                        requested_location=request.location,
                        requested_pano=request.pano,
                        requested_viewpoint=viewpoint,
                        location_resolution=LocationResolution(
                            display_text=request.location,
                            place_url=identity.canonical_url,
                            coordinates=viewpoint,
                            source="maps_place",
                        ),
                        unsupported_api_fields=unsupported,
                    ),
                    str(exc),
                )
            selected_pano = selected_panorama.pano_id
            selected_renderer = selected_panorama.renderer_url
            location_resolution = LocationResolution(
                display_text=request.location,
                place_url=identity.canonical_url,
                coordinates=viewpoint,
                source="maps_place_photo",
            )

        selected_coordinates = (
            selected_panorama.coordinates if selected_panorama is not None else viewpoint
        )
        viewpoint_value = (
            f"{selected_coordinates.lat},{selected_coordinates.lng}"
            if selected_coordinates is not None
            else None
        )
        url = build_street_view_url(
            viewpoint_value,
            request.heading,
            request.pitch,
            request.fov,
            selected_pano,
        )
        try:
            exchange, bootstrap, artifacts = await self._bootstrap(url, "street-view")
            orientation = extract_orientation_from_url(exchange.final_url)
            if request.heading is not None:
                orientation["heading"] = request.heading
            if request.pitch is not None:
                orientation["pitch"] = request.pitch
            if request.fov is not None:
                orientation["fov"] = request.fov

            if selected_renderer is not None:
                image = await self._download_renderer(
                    [], request, artifacts, preferred_url=selected_renderer
                )
            else:
                if viewpoint is None:
                    raise HttpAdapterError(
                        "Street View coordinate metadata requires a valid viewpoint."
                    )
                metadata_exchange = await self._client.get_path(
                    "https://www.google.com/maps/photometa/si/v1",
                    endpoint="street-view-metadata",
                    params=build_street_view_metadata_params(
                        viewpoint, bootstrap, self._settings.locale, None
                    ),
                    referer=url,
                )
                try:
                    metadata_text = metadata_exchange.body.decode("utf-8")
                    metadata = parse_xssi_json(metadata_text)
                except (UnicodeDecodeError, PayloadParseError) as exc:
                    raise HttpAdapterError("street-view-metadata returned malformed JSON.") from exc
                metadata_renderer = renderer_url_from_metadata(
                    metadata_text,
                    heading=request.heading,
                    pitch=request.pitch,
                    fov=request.fov,
                )
                image = await self._download_renderer(
                    metadata, request, artifacts, preferred_url=metadata_renderer
                )
                if image is None:
                    image = await self._download_renderer(
                        bootstrap.initialization_state, request, artifacts
                    )
            if image is not None:
                artifacts = artifacts.model_copy(update={"street_view_image": image.path})
            return ApiEnvelope(
                ok=image is not None,
                source="google_maps_web",
                request=request.model_dump(),
                maps_url=url,
                extracted=StreetViewExtracted(
                    requested_location=request.location,
                    requested_pano=request.pano,
                    requested_heading=request.heading,
                    requested_pitch=request.pitch,
                    requested_fov=request.fov,
                    requested_viewpoint=viewpoint,
                    location_resolution=location_resolution,
                    resolved_url=url,
                    resolved_coordinates=(
                        selected_panorama.coordinates
                        if selected_panorama is not None
                        else _coordinates(exchange.final_url, bootstrap) or viewpoint
                    ),
                    orientation=StreetViewOrientation(**orientation),
                    capture_date=(
                        selected_panorama.capture_date if selected_panorama is not None else None
                    ),
                    image_key=selected_pano,
                    image=image,
                    unsupported_api_fields=unsupported,
                ),
                artifacts=artifacts,
                confidence=Confidence(
                    overall="medium" if image is not None else "low",
                    notes=(
                        ["HTTP mode does not create a browser screenshot."]
                        if image is not None
                        else [
                            "HTTP mode does not create a browser screenshot and this Maps response "
                            "did not expose a safe clean renderer URL."
                        ]
                    ),
                ),
            )
        except (HttpAdapterError, BootstrapParseError) as exc:
            return self._error(
                request,
                url,
                StreetViewExtracted(
                    requested_location=request.location,
                    requested_pano=request.pano,
                    unsupported_api_fields=unsupported,
                ),
                str(exc),
            )

    async def _bootstrap(
        self, url: str, endpoint: str
    ) -> tuple[HttpExchange, MapsBootstrap, ArtifactSet]:
        exchange = await self._client.get(url, endpoint=endpoint)
        if "html" not in exchange.content_type:
            raise HttpAdapterError(
                f"{endpoint} returned {exchange.content_type or 'an unknown'} response, not HTML."
            )
        bootstrap = parse_maps_bootstrap(
            exchange.body.decode("utf-8", errors="replace"), exchange.final_url
        )
        return exchange, bootstrap, self._write_artifacts(endpoint, exchange)

    def _write_artifacts(self, endpoint: str, exchange: HttpExchange) -> ArtifactSet:
        directory = make_artifact_dir(Path(self._settings.artifact_dir), uuid.uuid4().hex)
        request_path = directory / "request.json"
        response_path = directory / "response.json"
        request_path.write_text(
            json.dumps(
                {"backend": self.name, "endpoint": endpoint, "url": exchange.requested_url},
                indent=2,
            ),
            encoding="utf-8",
        )
        response_path.write_text(
            json.dumps(
                {
                    "backend": self.name,
                    "endpoint": endpoint,
                    "final_url": exchange.final_url,
                    "status": exchange.status_code,
                    "content_type": exchange.content_type,
                    "bytes": len(exchange.body),
                    "attempts": exchange.attempts,
                    "parser_version": 1,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return ArtifactSet(response=str(response_path))

    async def _download_renderer(
        self,
        payload: object,
        request: StreetViewRequest,
        artifacts: ArtifactSet,
        *,
        preferred_url: str | None = None,
    ) -> StreetViewImage | None:
        renderer_url = preferred_url or next(
            (value for value in strings_in(payload) if _RENDERER_URL.fullmatch(value)),
            None,
        )
        if renderer_url is None or artifacts.response is None:
            return None
        width, height = (int(part) for part in (request.size or "640x360").lower().split("x", 1))
        renderer_url = build_renderer_url(
            renderer_url,
            width,
            height,
            request.fov,
            heading=request.heading,
            pitch=request.pitch,
        )
        exchange = await self._client.get(renderer_url, endpoint="street-view-image")
        if exchange.content_type not in {"image/jpeg", "image/png"}:
            return None
        try:
            width, height = image_dimensions(exchange.body)
        except ValueError as exc:
            raise HttpAdapterError("street-view-image returned invalid image bytes.") from exc
        extension = ".jpg" if exchange.content_type == "image/jpeg" else ".png"
        destination = Path(artifacts.response).parent / f"street-view{extension}"
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(exchange.body)
        temporary.replace(destination)
        return StreetViewImage(
            path=str(destination),
            width=width,
            height=height,
            content_type=exchange.content_type,
            source="web_renderer",
            clean=True,
        )

    def _error(
        self, request: BaseModel, maps_url: str | None, extracted: T, message: str
    ) -> ApiEnvelope[T]:
        return ApiEnvelope(
            ok=False,
            source="google_maps_web",
            request=request.model_dump(),
            maps_url=maps_url,
            extracted=extracted,
            artifacts=ArtifactSet(),
            confidence=Confidence(overall="low", notes=[message]),
        )


def _coordinates(url: str, bootstrap: MapsBootstrap) -> CoordinatePair | None:
    result = extract_coordinates_from_url(url) or first_coordinate(bootstrap.initialization_state)
    return CoordinatePair(lat=result[0], lng=result[1]) if result else None


def _observed_coordinates(observation: ObservedPlace | None) -> CoordinatePair | None:
    if observation is None or observation.coordinates is None:
        return None
    return CoordinatePair(
        lat=observation.coordinates.lat,
        lng=observation.coordinates.lng,
    )


def _parse_coordinate(value: str | None) -> CoordinatePair | None:
    if not value:
        return None
    match = re.fullmatch(r"\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*", value)
    return CoordinatePair(lat=float(match.group(1)), lng=float(match.group(2))) if match else None


def _duration_seconds(value: str) -> int | None:
    hours = re.search(r"(\d+)\s*(?:hr|hour)", value, re.IGNORECASE)
    minutes = re.search(r"(\d+)\s*(?:min|minute)", value, re.IGNORECASE)
    if hours is None and minutes is None:
        return None
    return (int(hours.group(1)) * 3600 if hours else 0) + (
        int(minutes.group(1)) * 60 if minutes else 0
    )


def _distance_meters(value: str) -> int | None:
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(ft|feet|mi|mile|miles|km|kilometer|kilometers|m|meter|meters)\b",
        value,
        re.IGNORECASE,
    )
    if match is None:
        return None
    amount = float(match.group(1))
    unit = match.group(2).casefold()
    factor = 1.0
    if unit in {"ft", "feet"}:
        factor = 0.3048
    elif unit in {"mi", "mile", "miles"}:
        factor = 1609.344
    elif unit in {"km", "kilometer", "kilometers"}:
        factor = 1000.0
    return round(amount * factor)


def _matrix_failure_status(notes: list[str]) -> str:
    normalized = " ".join(notes).casefold()
    if "proxy" in normalized or "timed out" in normalized or "timeout" in normalized:
        return "blocked"
    if "no route was returned" in normalized:
        return "zero_results"
    return "parse_error"
