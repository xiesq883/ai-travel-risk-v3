# Amap Web Service contract used by JourneyPilot

Base URL: `https://restapi.amap.com`

All calls require the Web Service key as the `key` query parameter.  The key is
server-side only.

## Endpoints

| Capability | Method/path | Key params | Normalized by |
| --- | --- | --- | --- |
| POI text search | `GET /v3/place/text` | `keywords`, `city`, `types`, `offset`, `page`, `extensions=base` | `amap_place_search.py` |
| Geocoding | `GET /v3/geocode/geo` | `address`, `city` | `amap_place_search.py` |
| Reverse geocoding | `GET /v3/geocode/regeo` | `location=lon,lat`, `extensions=base` | `amap_place_search.py` |
| Walking | `GET /v3/direction/walking` | `origin`, `destination` | `amap_route_search.py` |
| Public transit | `GET /v3/direction/transit/integrated` | `origin`, `destination`, `strategy=0` | `amap_route_search.py` |
| Driving | `GET /v3/direction/driving` | `origin`, `destination` | `amap_route_search.py` |
| Bicycling | `GET /v4/direction/bicycling` | `origin`, `destination` | `amap_route_search.py` |

`origin`/`destination`/`location` are **GCJ-02** `longitude,latitude` strings.
JourneyPilot converts from/to WGS-84 at the boundary.

## Success and refusal

- v3: `status == "1"` means success; `info` and `infocode` explain refusal.
- v4 bike: `errcode == 0` means success; `errmsg` explains refusal.
- Empty `pois` / `geocodes` / `paths` with success status means **no result**,
  not a transport error.

Common refusal codes:

| info | Meaning | Action |
| --- | --- | --- |
| `INVALID_USER_KEY` | key invalid | do not retry; check Web Service key |
| `USER_KEY_PLAT_NOMATCH` | wrong platform key | use a Web Service key |
| `INVALID_USER_SCODE` | security code/whitelist mismatch | check Amap console binding |
| `SERVICE_NOT_AVAILABLE` | service not enabled | enable the service in console |
| `INSUFFICIENT_PRIVILEGES` | no permission | check account/service permissions |
| `DAILY_QUERY_OVER_LIMIT` | daily quota | stop and report |
| `ACCESS_TOO_FREQUENT` | QPS/rate limit | back off |
| `CUQPS_HAS_EXCEEDED_THE_LIMIT` | concurrency limit | back off |

## Price semantics

- Transit `route.transits[].cost` is a published transit fare when present.
- It is per-person unless the provider explicitly states otherwise; the current
  project stores it as `total_cost_cny` with
  `fare_type="published_transit_fare"`.
- It is not a ticket booking quote and does not confirm inventory.
- Walking/driving responses do not provide a traveller fare; leave it null.
- Never convert a missing fare to zero.

## Provenance fields

Every normalized place/route carries:

- `provider="amap"`
- `source_url` (official docs page used for the contract)
- `retrieved_at` (UTC ISO 8601)
- `confidence_status` (`provider_returned` / `provider_returned_without_coordinates`)
- coordinate-system labels

The downstream `trip-dataset.v1` records `source_type`, `retrieved_at`,
`price_type` and `confidence` separately; map data must not be promoted to
`actual_quote` unless a real quote path supplies it.
