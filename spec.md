# Browser-backed Google Maps API research spec

This project exposes a best-effort API for Google Maps web data. Its default
`GMAPS_BACKEND=http` adapter sends fail-closed proxied raw HTTP requests from
Python. The optional `zendriver` adapter automates the web app in Chrome when
rendered evidence is required. Both adapters implement the same project-owned
request and response contracts.

This is not parity with Google Maps Platform APIs. In this document,
"replicable" means the browser can open the same Google Maps view and the
project can return structured data parsed from visible or otherwise
browser-observable Maps output. It does not mean the project can return the same
official response objects, status codes, service quotas, data stability, or
metadata that Google Maps Platform returns.

## API output contract

Each endpoint should return a JSON envelope with explicit provenance and
confidence instead of pretending that browser automation is a first-party API:

```json
{
  "ok": true,
  "source": "google_maps_web",
  "request": {},
  "maps_url": "https://www.google.com/maps/...",
  "extracted": {},
  "artifacts": {
    "screenshot": null,
    "raw_visible_text": null
  },
  "confidence": {
    "overall": "high",
    "notes": []
  }
}
```

Endpoint-specific schemas should live inside `extracted`. If the UI is
ambiguous, blocked, missing imagery, or changes shape, the endpoint should return
`ok: false` or a lower confidence value with the raw visible text and screenshot
artifact needed to debug the mismatch. Do not silently invent missing fields.

## Replicable features

| Feature | Official API shape | Browser / Maps URL approach | Project status |
| --- | --- | --- | --- |
| Street View interactive viewer | `StreetViewPanorama` renders a panorama and supports position, point of view, visibility, links, zoom, and events. `StreetViewService.getPanorama()` returns `StreetViewPanoramaData` for a matching coordinate location or pano request. Street View Static API accepts `location` as an address string or latitude/longitude pair, or `pano` as a panorama ID, plus optional `heading`, `pitch`, and `fov`. | Expose a Street View API-shaped request, then adapt it to the web app. For address `location` input, first resolve the address/place through Maps search or the project geocode flow, then open Street View with `map_action=pano` and a coordinate `viewpoint`. For coordinate `location`, use it directly as `viewpoint`. For `pano`, pass the pano ID to the URL as a best-effort hint. Capture Maps web panorama metadata and a clean Google-hosted perspective renderer when observed; retain the full viewport screenshot only as diagnostics. | Strong for opening and controlling the viewer. Partial for image and structured data: return current URL, requested location/viewpoint, current/derived heading, pitch, fov, a clean renderer image when available, an explicit screenshot fallback, and visible place labels. Do not claim full `StreetViewPanoramaData` or a first-party Static API response. |
| Street View by URL | Maps URLs support `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=lat,lng&heading=...&pitch=...&fov=...`. A `pano` ID can also be supplied. | Build the URL and open it in the automated browser. Prefer `viewpoint` as the durable request input. Use `pano` only as an optional hint. | Supported as a launch mechanism. Pano IDs are not durable identifiers; Google documents Street View locations and IDs as subject to change as imagery refreshes, and JS pano IDs are stable only within a browser session. |
| Map display | `google.maps.Map` accepts center, zoom, map type, controls, and layers. Maps URLs support `map_action=map`, `center`, `zoom`, `basemap`, and one `layer` value such as traffic, transit, or bicycling. | Build a map URL or drive the web app controls for layers and viewport changes. | Strong for opening a view. Partial for data extraction: return URL, requested center/zoom/basemap/layer, and visible labels or selected place card fields when present. |
| Directions | `DirectionsService.route()` accepts origin, destination, travel mode, waypoints, avoid flags, route alternatives, driving/transit options, language, region, unit system, and other fields, and returns a structured `DirectionsResult`. Google now marks the JS Directions service/renderer as legacy/deprecated, though still available with notice before discontinuation. | Expose a Directions API-shaped request, then adapt the supported subset to `https://www.google.com/maps/dir/?api=1&origin=...&destination=...&travelmode=...`. Maps URLs support waypoints separated by `|` and avoid values for ferries, highways, and tolls. The web app can also be driven manually to select modes and options. | Partial. Return parsed route summary, duration, distance, steps visible in the route panel, chosen mode, requested waypoints, selected avoid flags, and unsupported requested fields. Do not claim support for `optimizeWaypoints`, all route alternatives, detailed polyline geometry, traffic models, transit preferences, unit/language controls, or exact `DirectionsResult` parity until individually implemented and tested. |
| Geocoding / reverse geocoding | Geocoding APIs accept an address, latitude/longitude, or place ID and return address, geometry, place ID, plus code, types, and address components. They support filters such as bounds, region, language, and component restrictions depending on surface. | Expose a Geocoding API-shaped request, then adapt it to Maps web search, coordinate URLs, or "What's here?" workflows. Address/place-card fields such as ratings, hours, website, and phone belong to the place schema, not geocoding. | Partial. Good for single lookup workflows that display a place card or coordinate card. Return displayed address/coordinate text, coordinates parsed from URL/card, plus code when visible, place URL, and unsupported requested filters. Not a full geocoder: do not claim support for component restrictions, exhaustive candidates, or high-volume batch behavior. |
| Place search / place details | Places APIs separate Text Search/Nearby Search from Place Details. Text Search accepts a text query and optional bias/filter fields. Place Details uses a place ID plus a field mask to return requested place fields such as display name, formatted address, location, rating, opening hours, website, phone, photos, reviews, and types. | Search the Maps web app for a query or open a Maps place URL, then parse the visible place card and canonical URL. Treat field masks as requested output fields and report fields not exposed by the web app. | Partial. Strong for visible place-card fields. Weak for official field-mask parity, reviews, photos metadata, accessibility fields, and stable IDs unless a field is visibly present or covered by fixture-backed internal extraction. |
| Street View static image | Street View Static API returns a non-interactive image from HTTP parameters such as `size`, `location` or `pano`, `fov`, `heading`, and `pitch`. `location` can be an address string or latitude/longitude pair. It requires an API key and is billed per request; a digital signature is recommended for security and may be required for some account types. | Resolve the panorama through Maps web, extract a direct Google-hosted perspective renderer from canonical links or captured panorama metadata, and request the caller's size and horizontal field of view while preserving Google-derived yaw/pitch orientation. Address input is first resolved to coordinates. | Partial substitute only. The clean image can closely match Static API content but comes from an undocumented web renderer and is not a first-party Static API response. Return `clean=false` with the UI screenshot when no renderer is safely available. |
| Distance matrix | Distance Matrix / route matrix APIs accept multiple origins and destinations plus mode/options and return an element for each origin-destination pair with distance, duration, and status. | Expose a matrix-shaped request, then orchestrate repeated single-route browser lookups for each pair. | Narrow support only. Return `elements[][]` with per-element provenance, confidence, and partial failures. This is slow, fragile browser work, not true matrix API parity. |
| Elevation | Elevation APIs accept `locations` or a sampled `path` and return numeric elevation, resolution, and status values. | The Maps web app generally does not expose exact numeric elevation. Terrain view can only provide a visual map screenshot/viewport state. | Unsupported as an Elevation API substitute. A terrain screenshot may be a `map_view` artifact, but do not expose it as elevation data. |
| Time zone | Time Zone API accepts `location` and `timestamp` and returns `timeZoneId`, `timeZoneName`, raw UTC offset, and daylight-saving offset. | Some place cards show local time for known places, but not the structured time-zone response for arbitrary coordinates and timestamps. | Unsupported as a Time Zone API substitute. Visible local-time text belongs to place metadata and should not be promoted to time-zone output. |

## Structured data requirements

The project should define its own response schemas. Do not copy official Google
Maps API response objects wholesale unless each field is actually visible,
derivable from the canonical Maps URL, or captured from browser-observable state.
Each schema field should record an extraction source such as `url`, `visible_text`,
`accessibility_tree`, `screenshot`, or `internal_request_diagnostic`.

Prefer visible UI and accessibility snapshots as the primary extraction source.
Google Maps internal network responses can be useful while debugging, but their
payloads and `pb` parameters are private implementation details and should not be
the stable public contract.

### Backend capability boundary

`GMAPS_BACKEND=http` is the default and must use `GMAPS_PROXY_URL` for every
outbound request. It can return canonical Maps URLs, server-exposed structured
text, resolved coordinates, and a clean Street View renderer image only when a
safe Google-hosted image URL is present. It cannot truthfully return a rendered
Maps viewport screenshot, browser accessibility tree, or Playwright trace, so
those artifact fields are `null`. `GMAPS_BACKEND=zendriver` retains the browser
evidence workflow and uses the same proxy setting for Chrome and clean image
downloads. Public Zendriver 0.15.x supports navigation, response capture,
screenshots, and visible-text extraction, but not this project's optional
Playwright-compatible trace methods; an explicit trace request must fail with a
capability error when those methods are absent. Neither adapter may silently
fall back to the other.

### Request resource limits

All request models reject resource-intensive input before a backend starts work.
General text inputs are limited to 512 characters and collection-shaped filters
are limited to 25 entries. Directions accept at most 10 waypoints and must still
fit the 2,048-character Maps URL limit. Street View images are limited to 2,048
pixels per side and 4,194,304 total pixels. Browser viewports are limited to
4,096 pixels per side and 8,294,400 total pixels. Distance-matrix origins and
destinations must both be non-empty, each axis is limited to 10 entries, and the
Cartesian product is limited to 25 elements because every element performs a
separate directions lookup. Violations are request-validation errors and the
HTTP surface returns status 422 without invoking Chrome or outbound HTTP.

### Internal HTTP data

Browser traces show that Google Maps web does load structured internal data over
HTTP, but the payloads are undocumented nested arrays and encoded `pb`/`f.req`
messages rather than stable public API JSON. Treat them as a separate extraction
tier:

* `source: "visible"`: fields parsed from visible text, accessibility snapshots,
  canonical URLs, and screenshots. This is the default public contract.
* `source: "internal_request_diagnostic"`: fields observed in captured internal
  requests or responses. These can support debugging and experimental parsers,
  but each parser needs fixture tests because RPC names, array indexes, request
  IDs, and response shapes can change.
* `source: "internal_request_promoted"`: an internal field may be promoted into
  the public schema only after it is observed across multiple fixtures and has a
  visible or URL-derived fallback where possible.

Observed internal endpoints and request families:

| Endpoint / request family | Observed use | Contract decision |
| --- | --- | --- |
| `/maps/preview/directions?...pb=...` | A fresh directions trace captured the response body when tracing started before navigation. The 62 KB anti-XSSI-prefixed nested JSON contained resolved origin/destination names, coordinates, observed IDs, place ID-like tokens, route alternatives, durations, distances, bicycling elevation values, step fragments, route coordinate arrays, Street View thumbnail pano IDs/URLs, and destination time-zone-like fields. | Strong evidence that the web app receives more structured route data than the visible panel exposes. Keep it behind `internal_request_diagnostic` until parser fixture tests cover multiple locales, profiles, travel modes, and route shapes. Keep visible route-panel extraction as the primary implementation. |
| `/maps/_/MapsWizUi/data/batchexecute` with `/MapsPhotoService.ListEntityPhotos` | Place and Street View pages requested photo/entity imagery data. Street View requests included candidate image keys such as `CIHM...` IDs. | Useful for diagnostics and image metadata experiments. Do not treat returned image/photo IDs as durable unless separately validated. |
| `/maps/_/MapsWizUi/data/batchexecute` with `/MapsViewportService.GetViewportMetadata` | Place, coordinate, and map views requested viewport metadata for the current center, size, and map state. | Useful for sanity checks against canonical URLs; not a public schema source by default. |
| `/maps/_/MapsWizUi/data/batchexecute` with `/MapsMerchantStatusService.GetMerchantStatus` | Place and coordinate views requested merchant/status metadata. | Ignore for the first implementation unless a visible place-card field depends on it. |
| `/maps/_/MapsWizUi/data/batchexecute` with `/MapsTrafficService.GetAreaTraffic` | Map view with layer state requested area traffic data. | Candidate for future traffic-layer research, but not stable enough for the first public map schema. |
| Initial search/place document and preload responses | Coordinate lookup returned compact anti-XSSI-prefixed JSON containing decimal coordinates, DMS strings, plus code, and map viewport data. Place pages returned much larger nested payloads containing visible place fields plus extra optional data such as ads, tickets, regions, and time-zone-like strings. | Good evidence that structured data exists below the UI. Parse only fields that are also visible or covered by fixture tests. |

### `directions` request contract

The public directions endpoint should be shaped around the Directions request
model, while making the browser-supported subset explicit:

* `origin` and `destination`: address/place text, place ID-like input, or
  `lat,lng` coordinates.
* `travel_mode`: `driving`, `walking`, `bicycling`, or `transit` when Maps web
  exposes the mode for the route.
* `waypoints[]`: optional intermediate stops. Pass through to Maps URLs where
  supported and report any waypoint ordering actually displayed by the web app.
* `avoid[]`: supported URL values are ferries, highways, and tolls.
* `alternatives`: request visible alternatives when the web app offers them, but
  do not promise all official route alternatives.
* `units`, `language`, `region`, `departure_time`, `arrival_time`,
  `driving_options`, `transit_options`, `optimize_waypoints`, and similar
  official fields: accept only if the implementation has a tested browser
  mapping; otherwise echo them in `unsupported_api_fields[]`.

Browser implementation flow:

1. Build a Maps directions URL for the supported request subset.
2. Open the route panel, select the requested mode/options when the URL is not
   enough, and wait for visible route results.
3. Capture the selected route, visible alternatives, warnings, and Details steps.
4. Report unsupported requested fields instead of silently ignoring them.

### `directions` extracted schema

Minimum supported fields:

* `origin`: requested text, resolved display text, optional place ID and
  coordinates when present in the canonical URL.
* `destination`: requested text, resolved display text, optional place ID and
  coordinates when present in the canonical URL.
* `travel_mode`: selected mode plus visible alternative mode summaries.
* `routes[]`: visible route alternatives with `summary`, `duration_text`,
  `distance_text`, route label such as `via 4th Ave N`, and optional
  mode-specific metadata such as bicycling ascent/descent when displayed.
  `duration_seconds_approximate` and `distance_meters_approximate` are derived
  from rounded display strings and are not exact official Routes API
  measurements. Return all visible cards only when `alternatives=true`;
  otherwise return the selected route alone.
* `selected_route.steps[]`: visible turn-by-turn instruction text and per-step
  distance text after opening Details, plus an explicitly approximate
  `distance_meters_approximate` derived from that text. Preserve the route-list
  capture separately from the post-click Details capture so opening Details
  does not erase alternative-route evidence.
* `internal_request_candidates`: optional diagnostic fields from the directions
  response body, such as route coordinate arrays, per-step coordinates,
  maneuver-like fragments, Street View thumbnails, observed place IDs, and
  time-zone-like destination fields. These should not be enabled by default or
  treated as stable until promoted by fixture coverage.
* `warnings[]`: visible caution text, for example bicycling condition warnings.
* `unsupported_api_fields[]`: fields requested by callers that the web app did
  not expose, such as encoded polyline geometry, maneuver enums, traffic model,
  route alternatives beyond visible candidates, or optimized waypoint order.

### `geocode` request contract

The public geocoding endpoint should be shaped around Geocoding API inputs, not
place details:

* Forward geocoding accepts `address` text or a `place_id` when the implementation
  has a reliable browser mapping.
* Reverse geocoding accepts `latlng` coordinates. A successful result requires
  an address-bearing Maps place record tied to those coordinates. Coordinate,
  DMS, or plus-code text alone is not an address and must produce `ok=false`
  rather than a fabricated result. Cookie-free Maps web may not expose such a
  record even when the official Geocoding API returns an address.
* Optional filters such as `bounds`, `region`, `language`, `components`,
  `result_type`, and `location_type` must be reported as unsupported until a
  browser behavior is implemented and covered by fixtures.

Browser implementation flow:

1. For `address`, search the Maps web app and parse the resolved place/card URL.
2. For `latlng`, open a coordinate URL or use "What's here?" and parse the
   coordinate card.
3. For `place_id`, use it only if a tested Maps URL/search flow resolves it to a
   visible result.
4. Return geocoding fields only. Ratings, hours, website, phone, photos, and
   categories belong to the place endpoint.

### `geocode` extracted schema

Minimum supported fields:

* `input`: original address, place ID, or coordinates.
* `input_type`: `address`, `latlng`, or `place_id`.
* `formatted_address`: visible formatted address when Maps displays one.
* `display_name`: visible result title when present.
* `coordinates`: parsed from the canonical URL/card when present.
* `plus_code`: visible plus code when shown.
* `place_url`: current Maps URL and any resolved URL after the lookup.
* `address_components`, `types`, `partial_match`, `geometry.viewport`, and
  official geocoding status fields only when implemented with visible or
  fixture-backed extraction; otherwise include them in `unsupported_api_fields[]`.

### `place_search` and `place_details` request contract

Place search and details should be separate public operations:

* `place_search.query`: text query such as a name, address, category, or business
  search. Optional official filters such as location bias/restriction, included
  type, open-now, price, language, and region are unsupported until implemented.
* `place_details.place_id`: official place ID when the caller has one. When a
  validated `maps_url` is not available, callers should also provide
  `place_details.query` as a human-readable identity hint. The default HTTP
  backend rejects ID-only requests because Maps web cannot reliably select and
  prove the requested official ID from a public URL alone.
* `place_details.maps_url`: Maps place URL from a prior browser lookup.
* `place_details.query`: text query used either as a fallback when neither
  `place_id` nor URL is available or as the identity hint paired with an
  official `place_id`.
* `fields[]`: requested output fields. Treat this like a field mask for the
  project response, not a guarantee that Maps web exposes the official Places
  field.

Browser implementation flow:

1. Search Maps web for `place_search.query` or open the provided Maps URL.
2. For `place_details.place_id`, resolve it through a tested Maps URL/search flow
   before relying on it.
3. Parse visible place-card fields and canonical URL coordinates.
4. Return requested fields that are visible or fixture-backed, and list the rest
   in `unsupported_api_fields[]`.

### `place` extracted schema

Minimum supported fields:

* `query`: caller input and resolved search text.
* `name`, `category`, `rating`, `review_count`, and `price_level_text` when
  visible.
* `address`, `located_in`, `hours_summary`, `website`, `phone`, `plus_code`,
  and place detail URL when visible.
* `coordinates`: parsed from the canonical `/maps/place/.../@lat,lng,...` URL
  when present.
* `official_place_id`: only when an actual Places API place ID is provided by the
  caller or extracted through a tested, documented path. Official place IDs may
  be stored and refreshed according to Google guidance.
* `observed_maps_url_ids`: place ID-like URL tokens when present. Treat them as
  observed identifiers, not durable database keys, unless separately validated as
  official place IDs.
* `id_provenance`: how each identifier was obtained, such as `caller_place_id`,
  `url_token`, `visible_text`, or `internal_request_promoted`.
* `optional_sections`: visible but non-core cards such as admissions, tours,
  popular times, photos, and visitor updates. These should be opt-in fields
  because they vary heavily by place and region.
* `unsupported_api_fields[]`: requested Places fields that the web app did not
  expose, such as full reviews, photo metadata, accessibility options, payment
  options, or exact field-mask parity.

### `reverse_geocode` extracted schema

Minimum supported fields:

* `input_coordinates`: caller input.
* `display_coordinates_dms`: visible DMS coordinates when shown.
* `display_coordinates_decimal`: normalized decimal coordinates when shown.
* `plus_code`: visible plus code when shown.
* `nearest_address_or_place`: only when the web app displays one. A coordinate
  lookup can validly return no formatted street address.
* `place_url`: current Maps URL and any resolved URL after the lookup.

### `street_view` request contract

The public Street View endpoint should be shaped around the Street View Static
API request model, because that is the most useful caller contract:

* `location`: address/place text or `lat,lng` coordinates. This is the preferred
  durable input. Address text is resolved through Maps web search/geocoding
  before opening Street View. Coordinates are passed directly as the Street View
  URL `viewpoint`.
* `pano`: optional panorama ID. Use it only when the caller explicitly asks for a
  known panorama. Do not store it as the durable lookup key; also keep the
  original `location` when available.
* `heading`, `pitch`, and `fov`: requested camera orientation. Pass these
  through to the Street View URL when launching the web app and report both the
  requested values and the resolved URL tokens.
* `size` or `viewport`: desired image dimensions. `size` controls the clean web
  renderer when available; `viewport` is its fallback size and independently
  controls the diagnostic browser viewport. The clean image is not a first-party
  Street View Static API response.

Browser implementation flow:

1. If `location` is address/place text, search it in Maps and extract the
   resolved coordinates and place URL from the visible result or canonical URL.
2. Open `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=lat,lng`
   with optional `heading`, `pitch`, and `fov`.
3. If `pano` is provided, include it as the URL `pano` parameter, but treat it as
   an override/hint and record when Maps resolves to a different panorama.
4. Capture the panorama metadata response and decoded canonical/candidate links.
   Accept renderer URLs only from explicit HTTPS Google image hosts, reject empty
   panorama IDs, and use the requested size and horizontal `fov` where the observed
   renderer format supports them.
5. Validate the downloaded JPEG or PNG and return it as `extracted.image` with
   `source=web_renderer` and `clean=true`. Keep the full browser screenshot under
   diagnostic artifacts. If renderer discovery or validation fails, return the
   screenshot as `source=browser_screenshot`, `clean=false`, and lower confidence.

Unsupported or partial Street View API fields should be reported explicitly in
`unsupported_api_fields[]`. Examples include guaranteed exact panorama IDs,
official metadata status codes, static-image billing semantics, and full
`StreetViewPanoramaData` links or tile metadata.

### `street_view` extracted schema

Minimum supported fields:

* `requested_location`, `requested_pano`, `requested_heading`,
  `requested_pitch`, `requested_fov`, and requested screenshot `size` or
  `viewport` from the caller request.
* `location_resolution`: for address/place input, the resolved display text,
  place URL, coordinates, and extraction source used before Street View launch.
  For coordinate input, record that no address-resolution step was needed.
* `requested_viewpoint`: the coordinates ultimately passed to the Maps web
  Street View URL.
* `resolved_url`: the canonical Street View URL after Maps snaps to imagery.
* `resolved_coordinates`: parsed from the canonical `@lat,lng,3a,...` URL when
  available.
* `orientation`: heading/pitch/fov tokens parsed from the URL when available.
* `title`, `contributor`, `capture_date`, `image_key`, and visible availability
  messages when shown.
* `image`: primary image path, dimensions, content type, renderer-or-screenshot
  source, and a `clean` flag that prevents UI screenshots from being mislabeled.
* `screenshot`: diagnostic viewport screenshot path and dimensions retained for
  browser debugging and compatibility.

Do not promise all `StreetViewPanoramaData` fields. Links to adjacent panoramas,
tile metadata, and stable pano IDs are not guaranteed to be visible through the
web app.

### `map_view` request contract

The public map-view endpoint should be URL-shaped rather than a full
`google.maps.MapOptions` clone:

* `center`: `lat,lng` coordinates.
* `zoom`: requested zoom level when Maps URLs support it.
* `basemap`: supported Maps URL basemap values such as roadmap, satellite, or
  terrain where available.
* `layer`: at most one Maps URL layer such as traffic, transit, or bicycling.
* Other JavaScript map options such as custom controls, gesture handling,
  styling, custom overlays, and event listeners are unsupported in the browser
  API contract unless implemented as explicit project features.

### `map_view` extracted schema

Minimum supported fields:

* `requested_center`, `requested_zoom`, `requested_basemap`, and
  `requested_layer`.
* `resolved_url`: canonical URL after Maps normalizes the view.
* `resolved_center` and approximate resolved zoom/scale parsed from the
  canonical URL when available.
* `visible_controls`: layer, zoom, location, scale, and map attribution controls.
* `screenshot`: viewport screenshot path and dimensions.

Plain map views should not promise visible place labels as structured data unless
the label is selected or otherwise exposed in a side panel or accessible tree.

### `distance_matrix` request contract

The public distance-matrix endpoint should be shaped like a matrix request while
being explicit that the browser implementation loops over single-route lookups:

* `origins[]`: address/place text, place ID-like input, or `lat,lng`
  coordinates.
* `destinations[]`: address/place text, place ID-like input, or `lat,lng`
  coordinates.
* `travel_mode`, `avoid[]`, `units`, `language`, `region`, `departure_time`,
  `arrival_time`, `traffic_model`, and transit options follow the same support
  rules as the directions endpoint.
* The response must preserve matrix shape even when individual lookups fail.

Browser implementation flow:

1. For each origin/destination pair, run the supported directions lookup.
2. Parse the selected route distance and duration visible in the route panel.
3. Store per-element status, provenance, confidence, and artifacts.
4. Rate-limit and timeout the batch; never hide partial failures behind a single
   success flag.

### `distance_matrix` extracted schema

Minimum supported fields:

* `origins[]` and `destinations[]`: requested values and any resolved display
  text/coordinates.
* `elements[][]`: one row per origin and one element per destination.
* `elements[][].status`: `ok`, `zero_results`, `not_supported`, `timeout`,
  `blocked`, or `parse_error`.
* `elements[][].distance_text` and `elements[][].duration_text`: visible route
  panel values when available.
* `elements[][].route_summary`, `travel_mode`, `maps_url`, `confidence`, and
  optional screenshot/raw-text artifact references.
* `unsupported_api_fields[]`: matrix options requested by callers that were not
  applied to the browser lookup.

### Unsupported API-shaped endpoints

`elevation` is not a supported data endpoint. The official Elevation APIs return
numeric elevation and resolution for `locations` or sampled `path` requests; the
Maps web app generally exposes only visual terrain. Return `not_supported` for
Elevation API-shaped requests. If useful, callers may request a `map_view`
terrain screenshot as a separate visual artifact.

`time_zone` is not a supported data endpoint. The official Time Zone API requires
`location` and `timestamp` and returns `timeZoneId`, `timeZoneName`,
`rawOffset`, and `dstOffset`. Visible local time on a place card may be returned
as place metadata, but it must not be exposed as a Time Zone API response.

## Manual validation results

Validation date: 2026-06-21. Browser automation used Zendriver CLI with a headed
Chrome session and Playwright-compatible traces.

| Workflow | Test input | Browser-observed data | Artifacts |
| --- | --- | --- | --- |
| Directions | `Space Needle Seattle WA` to `Pike Place Market Seattle WA`, `travelmode=bicycling` | Visible travel mode summaries, selected cycling route, three route alternatives, duration/distance, route labels, bicycling ascent/descent, route warning, and Details step instructions with per-step distances. | `.playwright-cli/snapshot-1.yml`, `.playwright-cli/snapshot-4.yml`, `.playwright-cli/traces/trace-1782022087886.zip` |
| Place lookup | `Space Needle Seattle WA` | Canonical place URL with coordinates and observed IDs; visible name, rating, review count, category, price marker, description, address, hours summary, services link, website, phone, plus code, popular-times bars, and optional commercial cards. | `.playwright-cli/snapshot-5.yml`, `.playwright-cli/traces/trace-1782022087886.zip` |
| Street View URL | Eiffel Tower `map_action=pano` URL with viewpoint, heading, pitch, and fov | Canonical Street View URL with snapped coordinates and orientation tokens; visible title, contributor, capture date, copyright notice, image key in report URL, Street View controls, and screenshot. The accessibility tree can also show availability messages. | `.playwright-cli/snapshot-8.yml`, `.playwright-cli/streetview-validation.png`, `.playwright-cli/traces/trace-1782022087886.zip` |
| Coordinate lookup | `47.6205063,-122.3492774` | Visible DMS coordinates, decimal coordinates, plus code, and coordinate actions. No formatted street address was shown for this exact point. | `.playwright-cli/snapshot-12.yml`, `.playwright-cli/traces/trace-1782022183562.zip` |
| Map URL | `map_action=map` with center, zoom, satellite basemap, and transit layer | Canonical URL with center and map/layer tokens; visible map/search controls and screenshot. The plain map itself exposed little structured text through the accessibility tree. | `.playwright-cli/snapshot-13.yml`, `.playwright-cli/snapshot-15.yml`, `.playwright-cli/map-validation.png`, `.playwright-cli/traces/trace-1782022183562.zip` |
| Internal request inspection | Existing trace archives | Captured `batchexecute` and preview requests for photo/entity, viewport metadata, merchant status, traffic, and coordinate search data. Responses are anti-XSSI-prefixed JSON or large undocumented nested arrays, not stable public API response objects. | `.playwright-cli/traces/trace-1782022087886-summary.json`, `.playwright-cli/traces/trace-1782022183562-summary.json`, extracted `trace.network` files |
| Directions internal response | `Space Needle Seattle WA` to `Pike Place Market Seattle WA`, trace started before navigation | Captured `/maps/preview/directions` response body with resolved origin/destination details, route alternatives, duration/distance values, step fragments, route coordinate arrays, Street View thumbnail metadata, and time-zone-like fields. The captured session localized some text to French, which proves parsers must either pin locale or treat display strings as locale-dependent fixtures. | `.playwright-cli/traces/trace-1782024662358.zip`, `.playwright-cli/traces/trace-1782024662358-summary.json`, `.playwright-cli/traces/trace-1782024662358_extracted/resources/7f595809bb026e3f20d97ce0a623587be02d1a01.json` |

## Implementation priorities

1. Street View `location`/`pano` request adapter, URL launcher, and state
   extractor.
2. Geocode and reverse-geocode adapters that keep address/coordinate lookup
   separate from place details.
3. Place search/details adapter with field-request reporting and identifier
   provenance.
4. Single origin/destination directions extractor.
5. Map URL launcher and viewport/layer extractor.
6. Optional batch wrappers that call the single-lookups repeatedly and report
   partial failures instead of hiding them.

## Non-goals and guardrails

* Do not promise official Google Maps Platform response objects.
* Do not use pano IDs as durable database keys. Store original coordinates or
  address inputs and refresh the resolved panorama when needed.
* Do not treat Maps URL tokens as official Places IDs. Keep
  `official_place_id` separate from `observed_maps_url_ids` and record
  provenance for every identifier.
* Do not mix API families in the public contract. Geocoding returns address and
  geometry fields; Places returns business/place details; Time Zone and
  Elevation are unsupported unless a real structured extraction path is added.
* Do not expose a field unless it is visible, derivable from the URL, or
  explicitly captured from browser-observable state.
* Do not treat screenshots, visible text, DOM shape, or URL fragments as stable
  across Google Maps releases. Every parser needs fixture coverage and a
  fallback artifact for debugging.
* Do not parse internal request bodies without fixture tests. Internal response
  text and units can vary by locale/profile/consent state; pin language/region
  in test inputs where deterministic display strings matter.
* Do not treat browser automation as fast. Endpoints should have timeouts,
  retry limits, and clear `partial` or `low_confidence` results.

## Sources

* [Google Maps URLs guide](https://developers.google.com/maps/documentation/urls/get-started) - `map_action=map`, `map_action=pano`, Street View URL parameters, directions URL parameters, and waypoint examples. Last checked: 2026-06-21.
* [Street View JavaScript guide](https://developers.google.com/maps/documentation/javascript/streetview) - `StreetViewPanorama`, point-of-view behavior, heading, and pitch. Last checked: 2026-06-21.
* [Street View service reference](https://developers.google.com/maps/documentation/javascript/reference/street-view-service) - `StreetViewService.getPanorama()`, `StreetViewPanoramaData`, request fields, statuses, and pano ID stability note. Last checked: 2026-06-21.
* [Directions JavaScript reference](https://developers.google.com/maps/documentation/javascript/reference/directions) - `DirectionsService.route()`, `DirectionsRequest`, `DirectionsResult`, waypoint limitations, and deprecation notice. Last checked: 2026-06-21.
* [Street View Static API overview](https://developers.google.com/maps/documentation/streetview/overview) - API key, billing, request parameters, and signature recommendation. Last checked: 2026-06-21.
* [Street View Static API request guide](https://developers.google.com/maps/documentation/streetview/request-streetview) - `location`, `pano`, `size`, `heading`, `pitch`, `fov`, and pano ID refresh behavior. Last checked: 2026-06-21.
* [Geocoding API overview](https://developers.google.com/maps/documentation/geocoding/guides-v3/overview) - address, latitude/longitude, and place ID geocoding behavior. Last checked: 2026-06-21.
* [Geocoding API request guide](https://developers.google.com/maps/documentation/geocoding/guides-v3/requests-geocoding) - geocoding request parameters and response fields. Last checked: 2026-06-21.
* [Places Text Search guide](https://developers.google.com/maps/documentation/places/web-service/text-search) - text query and field-mask behavior for place search. Last checked: 2026-06-21.
* [Places Details guide](https://developers.google.com/maps/documentation/places/web-service/place-details) - place ID and field-mask behavior for place details. Last checked: 2026-06-21.
* [Place IDs guide](https://developers.google.com/maps/documentation/places/web-service/place-id) - storing and refreshing official place IDs. Last checked: 2026-06-21.
* [Distance Matrix API overview](https://developers.google.com/maps/documentation/distance-matrix/overview) - origins, destinations, travel options, and matrix response shape. Last checked: 2026-06-21.
* [Elevation API overview](https://developers.google.com/maps/documentation/elevation/overview) - numeric elevation data for locations and sampled paths. Last checked: 2026-06-21.
* [Time Zone API overview](https://developers.google.com/maps/documentation/timezone/overview) - `location`, `timestamp`, time zone ID, and offset response fields. Last checked: 2026-06-21.
