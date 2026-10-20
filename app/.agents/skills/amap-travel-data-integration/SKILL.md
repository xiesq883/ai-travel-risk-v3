---
name: amap-travel-data-integration
description: Integrate or debug Amap (高德) Web Service POI, geocoding and route data for the JourneyPilot travel planner. Use when a task mentions 高德, Amap, POI search, 地理编码, 逆地理编码, 步行/公交/驾车路线, or map provenance in the itinerary/risk pipeline.
---

# Amap Travel Data Integration

This skill is development guidance.  Runtime map queries must go through the
backend services listed below; creating or editing this skill does not mean the
application has a working Amap connection.

## When to use

Use this skill when:

- adding or changing Amap POI search, geocoding, reverse geocoding or routing;
- wiring a real map result into destination/accommodation/transport research;
- checking why a China itinerary has missing coordinates, distance or duration;
- reviewing provenance, fare or "unknown" semantics for map data.

Do not use it to add hotel live prices, restaurant menus or booking actions.
Amap POI data is identity/location data, not a price quote.

## Existing implementation (reuse, do not duplicate)

| Concern | Path |
| --- | --- |
| Shared key + rate gate | `src/travel_agent/services/amap_client.py` |
| POI / geocode / regeocode | `src/travel_agent/services/amap_place_search.py` |
| Walking / transit / driving / bike | `src/travel_agent/services/amap_route_search.py` |
| Route dispatch for China vs world | `src/travel_agent/services/global_route_search.py` |
| Model tools | `src/travel_agent/tools/builtin_tools.py` |
| Agent allowlists | `src/travel_agent/agents/utils.py` |
| Structured output | `src/travel_agent/entities/trip_dataset.py` |

The model-facing route tool is **`global_route_search`**.  Inside the China
coordinate box it calls Amap; elsewhere it calls Transitous/MOTIS.  Do not add a
second route tool that bypasses this dispatch.

## Key configuration

Supported names, in order:

1. `AMAP_WEB_SERVICE_KEY` (preferred for the standalone Web Service integration)
2. `AMAP_MAPS_API_KEY` (existing MCP-compatible name)

Put exactly one of them in the local `app/.env`:

```text
AMAP_WEB_SERVICE_KEY=...
```

Rules:

- never put the key in source, frontend code, tests, logs, docs or a Skill;
- `.env` is git-ignored; `.env.example` must stay empty;
- do not print the key on failure; errors name the failure class only;
- do not create a second conflicting key setting.

If the key is missing, `amap_place_search` returns `error_code="not_configured"`.
It must not fall back to a fabricated place.

## API selection

| Need | Use | Notes |
| --- | --- | --- |
| Find a scenic spot/restaurant/hotel | `amap_place_search` | returns POI ID, address, WGS-84 coordinates, adcode |
| Address → coordinates | `amap_geocode` | returns formatted address, level, adcode |
| Coordinates → address | `amap_regeocode` | returns address components and nearby POIs |
| Walking route | `global_route_search(mode="walk")` | AMap inside China |
| Public transit route | `global_route_search(mode="public_transit")` | fare only when AMap returns `cost` |
| Driving route | `global_route_search(mode="drive")` | duration is an estimate, not a guarantee |
| Weather | existing Open-Meteo path | do not add Amap weather unless compatibility is proven |

Official docs:

- Web Service: https://lbs.amap.com/api/webservice/gettingstarted
- Route: https://lbs.amap.com/api/webservice/guide/api/newroute
- Direction: https://lbs.amap.com/api/webservice/guide/api/direction

## Coordinates and units

- Internal project coordinates: **WGS-84**.
- Amap requests/responses: **GCJ-02**.
- Convert at the service boundary with
  `src/travel_agent/utils/coordinates.py`.
- Internal distances: metres (`distance_meters`), durations: minutes
  (`duration_minutes`).  Do not mix seconds into itinerary fields.
- Never mix a GCJ-02 point with a WGS-84 endpoint; that produces a silent offset.

## Normalized place result

`amap_place_search` / `amap_geocode` return:

- `place_id` (`amap:<poi-id>` or `amap:geocode:...`)
- `name`, `address`
- `latitude`, `longitude` (WGS-84)
- `city`, `district`, `province`, `adcode`
- `typecode`, `type`, `provider`
- `provider_place_type`, `provider_country_code`
- `confidence_status` (`provider_returned` or
  `provider_returned_without_coordinates`)
- `source_url`, `retrieved_at`
- `coordinate_system="WGS84"`, `raw_coordinate_system="GCJ-02"`

An empty result is `success=true, places=[], message="no_result"`.  A provider
error is `success=false` with an `error_code`.  These are different facts.

## Route normalization

Use `global_route_search`; it returns `routes[0]` with:

- endpoints, `selected_mode`, `transport_class`
- `duration_minutes`, `distance_meters`
- `segments` (walk/line/ride)
- `total_cost_cny` only when the provider returned `cost`
- `fare_type="published_transit_fare"` when a fare exists
- `currency="CNY"` only when a fare exists

Do not turn a missing fare into `0`.  Do not call a transit fare a confirmed
ticket price.  Do not describe an estimated driving duration as guaranteed.

## Error handling

| Failure | Required behaviour |
| --- | --- |
| no key | `not_configured`; keep fields unknown, tell the user how to configure |
| HTTP timeout | `timeout`; no retry loop beyond the existing budget |
| invalid key / platform mismatch | `provider_refused`; do not retry blindly |
| quota/rate limit | `provider_refused`/rate-limit message; back off |
| empty POI result | success + empty list, not an error |
| provider refusal | do not treat as "no route" |
| missing coordinates | keep null; do not invent a point |
| missing fare | `price_type="unknown"` downstream |

The full API and error-code reference is in
[references/api-contract.md](references/api-contract.md).

## Integration rules

1. Add map capabilities to the existing agent allowlists in
   `agents/utils.py`; do not build a second agent framework.
2. Destination/accommodation research may call POI/geocode tools.
3. Transport research must use `global_route_search`; never author a route from
   model memory and mark it `ready`.
4. A returned POI becomes a candidate/place with its `place_id`, coordinates and
   source.  A route becomes a `TransportLeg`/dataset route with distance,
   duration, fare state and `retrieved_at`.
5. Keep `trip-dataset.v1` compatibility: no renaming of existing fields; add
   optional fields only.

## Tests

Run:

```powershell
$env:PATH="$pkg\runtime\postgres\bin;$env:PATH"
& "$pkg\runtime\python\python.exe" -m pytest tests/test_amap_place_search.py tests/test_amap_route_search.py -q
```

Also run the full backend suite and frontend `npm.cmd run check` when the
change touches generated output.

Mocked tests must cover: POI success, empty result, geocode, regeocode, missing
key, timeout, invalid key, permission/rate-limit, missing fare, and no-route.
Label mocked responses as mocked; never call them "real API verified".

Real verification (only when a key is configured locally):

```powershell
& "$pkg\runtime\python\python.exe" scripts\verify_amap.py
```

The script must not print the key.  Record the real result separately from the
mocked test result.
