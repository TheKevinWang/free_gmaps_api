# Free Google Maps API

A self-hosted API wrapper for the Google Maps web app, using direct HTTP
requests or Zendriver browser automation. Only a subset of Google Maps
functionality is supported because the web app does not expose everything
available through Google's official APIs.

This is an independent experimental project. Read [DISCLAIMER.md](DISCLAIMER.md)
before using or redistributing it.

## What it can do

| Capability | Plain-English description | Important limitation |
| --- | --- | --- |
| Street View | Finds a panorama and may save a clean perspective image. | The renderer is an undocumented web feature and may change. |
| Geocoding | Turns an address or place hint into displayed coordinates. | It is not a complete official geocoder. |
| Reverse geocoding | Tries to find an address associated with coordinates. | It fails when Maps does not expose a trustworthy address-bearing record. |
| Place search/details | Returns visible place information such as name, address, rating, and coordinates. | Some official fields and ID-only lookups are unavailable. |
| Directions | Returns visible routes, distances, durations, warnings, and steps. | Normalized meters and seconds are approximate. |
| Map view | Opens a requested center, zoom, map type, or layer. | Browser screenshots are available only with the browser backend. |
| Distance matrix | Repeats directions lookups for several origin/destination pairs. | Limited to 25 elements and unsuitable for high-volume work. |
| Elevation and time zone | Returns an explicit `not_supported` response. | The website does not expose a stable substitute. |

## Quick start for Windows

### 1. Install the prerequisites

You need:

- Windows with Python 3.12 or newer.
- `uv` for creating the Python environment and installing the project.
- A working HTTP or SOCKS5 proxy.

The proxy is mandatory. The service deliberately refuses to connect directly
when the configured proxy is unavailable. The default is
`socks5://localhost:9050`. If you do not know what proxy endpoint you should
use, resolve that before continuing.

Chrome is not needed for the default mode. It is needed only for optional
browser-rendered evidence.

### 2. Install the service

Run these commands from the repository directory in PowerShell:

    uv venv --seed .venv
    uv pip install --python .\.venv\Scripts\python.exe -e .

If your proxy is not running at the default address, set it for the current
PowerShell window:

    $env:GMAPS_PROXY_URL = "socks5://127.0.0.1:9050"

Replace that example with your real proxy scheme, host, and port.

### 3. Start the service

    .\.venv\Scripts\python.exe -m uvicorn free_gmaps_api.app:create_app --factory --host 127.0.0.1 --port 8787

Keep that window open. The service is available only on your computer at
`http://127.0.0.1:8787` unless you deliberately bind it elsewhere.

### 4. Confirm that it is running

Open a second PowerShell window and run:

    Invoke-RestMethod http://127.0.0.1:8787/health

A healthy response looks like this:

    ok      version backend
    --      ------- -------
    True    0.1.0   http

### 5. Try a request

The easiest interface is the interactive documentation at
[http://127.0.0.1:8787/docs](http://127.0.0.1:8787/docs). Open an endpoint,
select **Try it out**, enter its JSON request, and select **Execute**.

This PowerShell example requests coordinates for the Space Needle:

    $body = @{ address = "Space Needle Seattle WA" } | ConvertTo-Json

    Invoke-RestMethod `
      http://127.0.0.1:8787/v1/geocode `
      -Method Post `
      -ContentType "application/json" `
      -Body $body

Press `Ctrl+C` in the server window when you want to stop it.

## Use with `gogcli`

[`gogcli`](https://github.com/openclaw/gogcli) can use a running instance of
this service as its explicit `free-gmaps` Maps provider. These commands do not
need a Google Maps API key or Google OAuth credentials, and they never fall back
to the official, potentially billed Google provider.

Open a separate PowerShell window in the root of your `gogcli` checkout. Source
builds require the Go version declared in `gogcli`'s `go.mod`:

    New-Item -ItemType Directory -Force .\bin | Out-Null
    go build -o .\bin\gog.exe .\cmd\gog

Keep `free_gmaps_api` running as described above, then point the CLI at it by
selecting `--provider free-gmaps` on each Maps command:

    $gog = Join-Path (Get-Location) "bin\gog.exe"

    & $gog maps geocode "Space Needle Seattle WA" `
      --provider free-gmaps --json

    & $gog maps places search "Space Needle Seattle WA" `
      --provider free-gmaps --json

    & $gog maps directions `
      --origin "Space Needle Seattle WA" `
      --destination "Pike Place Market Seattle WA" `
      --mode walking `
      --provider free-gmaps --json

The same provider is available for `reverse-geocode`, `distance`, place
details, and Street View. Place details has one extra requirement: because Maps
web cannot reliably prove an official place ID by itself, supply a human-readable
query along with the ID:

    & $gog maps places details ChIJ-bfVTh8VkFQRDZLQnmioK9s `
      --query "Space Needle Seattle WA" `
      --provider free-gmaps --json

For Street View, set an absolute artifact directory **before** starting the
service. `gog` only copies image artifacts from a loopback service, because a
remote server's local file paths are not downloadable URLs:

    # Run this from the free_gmaps_api checkout before starting Uvicorn.
    $env:GMAPS_ARTIFACT_DIR = Join-Path (Get-Location) ".free-gmaps-api\artifacts"

    # Run this after the service is listening.
    & $gog maps street-view "Space Needle Seattle WA" `
      --provider free-gmaps `
      --out .\street-view.jpg --json

The provider expects `http://127.0.0.1:8787` by default. Use
`--free-gmaps-base-url` when the service listens elsewhere, and increase the
45-second client timeout for a cold browser workflow if necessary (the maximum
is two minutes). Plain HTTP base URLs are accepted only for loopback hosts;
remote services must use HTTPS:

    & $gog maps geocode "Space Needle" `
      --provider free-gmaps `
      --free-gmaps-base-url http://127.0.0.1:9000 `
      --free-gmaps-timeout 90s --json

With `--json`, free-provider output keeps the normal result key and adds
`provider` and `quality` fields containing confidence, approximation, and
unsupported-field information. Plain-text output keeps its usual columns and
writes these quality warnings to stderr. If `--provider` is omitted, `gog`
uses its official Google provider instead.

## Understanding a response

Every endpoint uses the same high-level envelope:

    {
      "ok": true,
      "source": "google_maps_web",
      "request": {},
      "maps_url": "https://www.google.com/maps/...",
      "extracted": {},
      "artifacts": {},
      "confidence": {
        "overall": "medium",
        "notes": []
      }
    }

The important fields are:

- `ok`: whether the tool found enough evidence to call the request successful.
- `extracted`: the useful result, such as coordinates or route information.
- `confidence`: how strongly the observed website evidence supports the result.
- `unsupported_api_fields`: requested options that the tool could not honor.
- `artifacts`: diagnostic files such as screenshots or visible text.

`ok=false` is an intentional result, not necessarily a server crash. The tool
fails closed when it cannot support a claim rather than inventing data.

## Common examples

### Directions

    $body = @{
      origin = "Space Needle Seattle WA"
      destination = "Pike Place Market Seattle WA"
      travel_mode = "bicycling"
      alternatives = $true
      optimize_waypoints = $true
    } | ConvertTo-Json -Depth 5

    Invoke-RestMethod `
      http://127.0.0.1:8787/v1/directions `
      -Method Post `
      -ContentType "application/json" `
      -Body $body

If an option such as `optimize_waypoints` is not implemented, the response lists
it under `extracted.unsupported_api_fields` instead of silently pretending it
worked. With `alternatives=true`, the result includes the route cards observed
on Maps. Distances and durations are normalized from displayed text and are
explicitly approximate.

### Street View image

    $body = @{
      location = "520 Vine St, Cincinnati, OH 45202"
      heading = 45
      pitch = 0
      fov = 80
      size = "640x360"
      viewport = @{ width = 1280; height = 720 }
    } | ConvertTo-Json -Depth 5

    Invoke-RestMethod `
      http://127.0.0.1:8787/v1/street-view `
      -Method Post `
      -ContentType "application/json" `
      -Body $body

Street View inputs have different meanings:

- An address selects the Street View preview associated with that Maps place.
- A `lat,lng` location asks for nearby imagery at those coordinates.
- A `pano` value asks for that exact panorama ID.

The tool does not silently replace a failed address selection with unrelated
nearby imagery. When Maps exposes a safe renderer, `extracted.image` describes a
clean JPEG with `source: "web_renderer"`. The browser backend can fall back to a
full Maps UI screenshot, which is labeled `clean: false`.

## Technical reference

### Backends

A backend is the mechanism used to obtain evidence from the website.

| Backend | When to use it | Chrome required | Browser artifacts |
| --- | --- | --- | --- |
| `http` | Default. Faster requests where raw web responses contain enough evidence. | No | No screenshots, accessibility trees, or traces. |
| `zendriver` | When a rendered page, interaction, screenshot, or visible browser state is required. | Yes | Screenshots, visible text, accessibility summaries, and optional traces when supported. |

Both backends use `GMAPS_PROXY_URL` and fail closed if the proxy is unavailable.
They implement the same public request and response models and never silently
fall back to one another.

Browser operations are serialized through one managed Chrome session. If the
Chrome DevTools connection dies, the navigation is recorded, Chrome is replaced,
and that navigation is retried once. This design favors explainable evidence,
not throughput.

### Optional browser installation

Install Chrome, then add public Zendriver 0.15.x:

    uv pip install --python .\.venv\Scripts\python.exe -e ".[browser]"

Start the service in browser mode:

    $env:GMAPS_BACKEND = "zendriver"
    .\.venv\Scripts\python.exe -m uvicorn free_gmaps_api.app:create_app --factory --host 127.0.0.1 --port 8787

The integration is tested against the public
[cdpdriver/zendriver](https://github.com/cdpdriver/zendriver) source. Public
Zendriver supports normal navigation, response capture, screenshots, and
visible-text extraction. It does not currently expose this project's optional
Playwright-compatible trace methods. Setting `GMAPS_TRACE=true` with the public
package therefore returns a clear capability error instead of silently omitting
a requested trace.

### Endpoints

- `GET /health`
- `POST /v1/street-view`
- `POST /v1/geocode`
- `POST /v1/reverse-geocode`
- `POST /v1/place-search`
- `POST /v1/place-details`
- `POST /v1/directions`
- `POST /v1/map-view`
- `POST /v1/distance-matrix`
- `POST /v1/elevation` — explicit `not_supported` response
- `POST /v1/time-zone` — explicit `not_supported` response

The complete research contract and extraction rules are in [spec.md](spec.md).

### Request limits

The service validates work before it starts:

- General text inputs: at most 512 characters.
- Directions: at most 10 waypoints and a 2,048-character generated Maps URL.
- Street View images: at most 2,048 pixels per side and 4,194,304 pixels total.
- Browser viewports: at most 4,096 pixels per side and 8,294,400 pixels total.
- Distance matrices: non-empty axes, at most 10 values per axis and 25 elements total.

Invalid requests receive HTTP 422 without starting Chrome or making an outbound
request.

### Configuration

Settings use the `GMAPS_` environment prefix.

| Setting | Default | Meaning |
| --- | --- | --- |
| `GMAPS_BACKEND` | `http` | Select `http` or `zendriver`. |
| `GMAPS_PROXY_URL` | `socks5://localhost:9050` | Mandatory outbound HTTP/SOCKS5 proxy. |
| `GMAPS_HEADLESS` | `true` | Run Chrome without a visible window. |
| `GMAPS_LOCALE` | `en-US` | Browser language and parsing locale. |
| `GMAPS_ARTIFACT_DIR` | `.free-gmaps-api/artifacts` | Diagnostic output directory. |
| `GMAPS_TIMEOUT_SECONDS` | `30` | Navigation and capture timeout. |
| `GMAPS_NAVIGATION_SETTLE_SECONDS` | `5` | Wait after navigation before extraction. |
| `GMAPS_INTERACTION_SETTLE_SECONDS` | `2` | Wait after an in-page interaction. |
| `GMAPS_TRACE` | `false` | Request a Playwright-compatible trace when the installed Zendriver supports it. |
| `GMAPS_HOST` | `127.0.0.1` | Documented launcher host default. |
| `GMAPS_PORT` | `8787` | Documented launcher port default. |

Uvicorn command-line arguments control the actual listening host and port in the
commands shown above. Keeping the service on `127.0.0.1` prevents other machines
from reaching it. If you expose it to a network, you are responsible for adding
appropriate authentication, rate limiting, and transport security.

### Known limitations

- Google can change the website or internal response shapes without notice.
- Results are web observations, not official Google Maps Platform responses.
- Reverse geocoding fails when Maps exposes coordinates but no trustworthy address record.
- Place details by official ID should include a human-readable `query` hint or a validated `maps_url`.
- Directions and matrix values are derived from displayed text and can differ from official route selection or timing.
- Clean Street View renderer URLs are undocumented and can stop working.
- Maps and Street View content may require attribution and may be restricted from storage or redistribution.

### Development setup and validation

Install the development tools and optional browser dependency:

    uv pip install --python .\.venv\Scripts\python.exe -e ".[dev,browser]"

Run the deterministic checks:

    .\.venv\Scripts\python.exe -m ruff format --check .
    .\.venv\Scripts\python.exe -m ruff check .
    .\.venv\Scripts\python.exe -m mypy src tests
    .\.venv\Scripts\python.exe -m pytest -m "not live and not official"

Run live browser checks only when real Google Maps traffic and local artifacts
are intentional:

    $env:GMAPS_LIVE = "1"
    .\.venv\Scripts\python.exe -m pytest -m live
    Remove-Item Env:GMAPS_LIVE

Run the raw HTTP live lane:

    $env:GMAPS_BACKEND = "http"
    $env:GMAPS_LIVE_HTTP = "1"
    .\.venv\Scripts\python.exe -m pytest tests/live/test_live_http.py -m live_http -vv
    Remove-Item Env:GMAPS_LIVE_HTTP

The optional official comparison lane can use billable Google APIs. Never save
its key in source, fixtures, traces, or shell transcripts:

    $env:GOOGLE_OFFICIAL_COMPARE = "1"
    $env:GOOGLE_MAPS_API_KEY = "<key>"
    .\.venv\Scripts\python.exe -m pytest -m official
    Remove-Item Env:GOOGLE_MAPS_API_KEY
    Remove-Item Env:GOOGLE_OFFICIAL_COMPARE

### Diagnostics, privacy, and cleanup

Browser requests can write:

- `request.json`: requested URL, viewport, and interaction information.
- `response.json`: resolved URL, retry history, capture metadata, and artifact paths.
- `screenshot.png`: final browser viewport.
- `street-view.jpg` or `street-view.png`: clean panorama image when available.
- `street-view-metadata.txt`: observed panorama metadata.
- `visible-text.txt`: text visible on the rendered page.
- `accessibility.json`: bounded roles, accessible names, text, and links.
- `trace.zip`: actions, network traffic, snapshots, and resources when enabled.
- `browser.log`: exception details and trace location after failures.

Treat the entire artifact directory as sensitive. A trace can contain complete
URLs, query values, headers, request and response bodies, browser snapshots,
cookies, and session identifiers. Visible-text and request metadata can contain
the caller's search terms. Inspect artifacts before sharing them and never run a
trace-enabled process with unrelated credentials available.

After the server and tests have stopped, remove ignored runtime evidence with:

    Remove-Item -LiteralPath .free-gmaps-api -Recurse -Force

The `.playwright`, `.playwright-cli`, `.playwright-mcp`, and `.zendriver-mcp`
directories are operator-tool workspaces and are ignored by Git. Remove them only
when no related browser or CLI session is running.
