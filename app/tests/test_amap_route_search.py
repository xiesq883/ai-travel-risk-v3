import httpx
import pytest

from travel_agent.services import amap_route_search
from travel_agent.services.amap_route_search import (
    AmapRouteSearchError,
    _normalize_route,
    search_amap_route_raw,
)


ORIGIN = {"name": "雷峰塔", "place_id": "amap:B001", "latitude": 30.2311, "longitude": 120.1489}
TARGET = {"name": "灵隐寺", "place_id": "amap:B002", "latitude": 30.2409, "longitude": 120.1022}


def test_walking_route_preserves_distance_and_unknown_fare():
    payload = {
        "status": "1",
        "route": {"paths": [{"distance": "1200", "duration": "900"}]},
    }
    route = _normalize_route(payload, mode="walk", origin=ORIGIN, destination=TARGET)
    assert route["distance_meters"] == 1200
    assert route["duration_minutes"] == 15
    assert route["total_cost_cny"] is None
    assert route["fare_type"] is None
    assert route["currency"] is None
    assert route["segments"][0]["mode"] == "walk"


def test_transit_route_parses_segments_and_published_fare():
    payload = {
        "status": "1",
        "route": {
            "transits": [
                {
                    "cost": "4.0",
                    "duration": "1500",
                    "distance": "5000",
                    "segments": [
                        {
                            "walking": {"distance": "300", "duration": "240"},
                            "bus": {
                                "buslines": [
                                    {
                                        "name": "地铁1号线",
                                        "type": "地铁线路",
                                        "duration": "1200",
                                        "distance": "4500",
                                        "departure_stop": {"name": "龙翔桥", "location": "120.1600,30.2500"},
                                        "arrival_stop": {"name": "定安路", "location": "120.1650,30.2450"},
                                    }
                                ]
                            },
                        }
                    ],
                }
            ]
        },
    }
    route = _normalize_route(payload, mode="public_transit", origin=ORIGIN, destination=TARGET)
    assert route["selected_mode"] == "metro"
    assert route["duration_minutes"] == 25
    assert route["total_cost_cny"] == 4.0
    assert route["fare_type"] == "published_transit_fare"
    assert route["currency"] == "CNY"
    assert [segment["mode"] for segment in route["segments"]] == ["walk", "metro"]


def test_transit_without_cost_stays_unknown():
    payload = {
        "status": "1",
        "route": {
            "transits": [
                {
                    "duration": "600",
                    "distance": "800",
                    "segments": [
                        {
                            "walking": {"distance": "800", "duration": "600"},
                        }
                    ],
                }
            ]
        },
    }
    route = _normalize_route(payload, mode="public_transit", origin=ORIGIN, destination=TARGET)
    assert route["total_cost_cny"] is None
    assert route["fare_type"] is None
    assert route["currency"] is None


def test_driving_route_has_no_fare_and_no_route_is_none():
    payload = {
        "status": "1",
        "route": {"paths": [{"distance": "3000", "duration": "600"}]},
    }
    route = _normalize_route(payload, mode="drive", origin=ORIGIN, destination=TARGET)
    assert route["total_cost_cny"] is None
    assert route["distance_meters"] == 3000
    assert _normalize_route({"status": "1", "route": {"paths": []}}, mode="drive", origin=ORIGIN, destination=TARGET) is None


@pytest.mark.asyncio
async def test_route_provider_refusal_and_timeout_are_not_no_route(monkeypatch):
    monkeypatch.setattr(amap_route_search, "_api_key", lambda: "test-key")

    def refusal(request):
        return httpx.Response(
            200,
            json={"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(refusal)) as client:
        with pytest.raises(AmapRouteSearchError):
            await search_amap_route_raw(
                from_latitude=30.2311,
                from_longitude=120.1489,
                to_latitude=30.2409,
                to_longitude=120.1022,
                mode="walk",
                client=client,
            )

    def timeout(request):
        raise httpx.TimeoutException("timed out")

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(AmapRouteSearchError):
            await search_amap_route_raw(
                from_latitude=30.2311,
                from_longitude=120.1489,
                to_latitude=30.2409,
                to_longitude=120.1022,
                mode="walk",
                client=client,
            )
