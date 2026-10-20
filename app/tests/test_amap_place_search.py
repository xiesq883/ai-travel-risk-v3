import httpx
import pytest

from travel_agent.services import amap_client
from travel_agent.services.amap_client import (
    AmapNotConfigured,
    AmapResponseError,
    AmapTimeout,
)
from travel_agent.services.amap_place_search import (
    amap_geocode,
    amap_poi_search,
    amap_regeocode,
)
from travel_agent.tools import builtin_tools
from travel_agent.utils.coordinates import gcj02_to_wgs84


def client_with(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def poi_payload():
    return {
        "status": "1",
        "info": "OK",
        "infocode": "10000",
        "pois": [
            {
                "id": "B001",
                "name": "雷峰塔",
                "address": "西湖区南山路",
                "location": "120.1489,30.2311",
                "cityname": "杭州市",
                "adname": "西湖区",
                "pname": "浙江省",
                "adcode": "330106",
                "typecode": "110202",
                "type": "风景名胜;公园广场;公园",
            }
        ],
    }


@pytest.mark.asyncio
async def test_poi_search_normalizes_identity_and_wgs84(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=poi_payload())

    async with client_with(handler) as client:
        result = await amap_poi_search(
            keywords="雷峰塔", city="杭州", limit=3, client=client
        )

    place = result["places"][0]
    expected_lon, expected_lat = gcj02_to_wgs84(120.1489, 30.2311)
    assert seen["path"] == "/v3/place/text"
    assert seen["params"]["city"] == "杭州"
    assert place["place_id"] == "amap:B001"
    assert place["name"] == "雷峰塔"
    assert place["adcode"] == "330106"
    assert place["longitude"] == pytest.approx(expected_lon, abs=1e-6)
    assert place["latitude"] == pytest.approx(expected_lat, abs=1e-6)
    assert place["provider"] == "amap"
    assert place["confidence_status"] == "provider_returned"
    assert place["retrieved_at"]
    assert "test-key" not in str(result)


@pytest.mark.asyncio
async def test_poi_empty_result_is_success(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")

    def handler(request):
        return httpx.Response(
            200,
            json={"status": "1", "info": "OK", "infocode": "10000", "pois": []},
        )

    async with client_with(handler) as client:
        result = await amap_poi_search(keywords="不存在的地点", client=client)
    assert result["success"] is True
    assert result["count"] == 0
    assert result["message"] == "no_result"
    assert result["places"] == []


@pytest.mark.asyncio
async def test_geocode_and_regeocode(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")

    def handler(request):
        if request.url.path == "/v3/geocode/geo":
            return httpx.Response(
                200,
                json={
                    "status": "1",
                    "info": "OK",
                    "geocodes": [
                        {
                            "formatted_address": "浙江省杭州市西湖区雷峰塔",
                            "location": "120.1489,30.2311",
                            "adcode": "330106",
                            "level": "兴趣点",
                            "city": "杭州市",
                            "district": "西湖区",
                            "province": "浙江省",
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "regeocode": {
                    "formatted_address": "浙江省杭州市西湖区南山路",
                    "addressComponent": {
                        "province": "浙江省",
                        "city": "杭州市",
                        "district": "西湖区",
                        "township": "西湖街道",
                        "adcode": "330106",
                    },
                    "pois": [],
                },
            },
        )

    async with client_with(handler) as client:
        geo = await amap_geocode(address="雷峰塔", city="杭州", client=client)
        regeo = await amap_regeocode(
            latitude=30.2311, longitude=120.1489, client=client
        )
    assert geo["places"][0]["level"] == "兴趣点"
    assert geo["places"][0]["adcode"] == "330106"
    assert regeo["result"]["address"] == "浙江省杭州市西湖区南山路"
    assert regeo["result"]["district"] == "西湖区"


@pytest.mark.asyncio
async def test_invalid_key_is_a_provider_refusal_without_echoing_key(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "secret-key-value")

    def handler(request):
        return httpx.Response(
            200,
            json={"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"},
        )

    async with client_with(handler) as client:
        with pytest.raises(AmapResponseError) as exc:
            await amap_poi_search(keywords="雷峰塔", client=client)
    assert exc.value.code == "provider_refused"
    assert "secret-key-value" not in str(exc.value)
    assert "Key" in str(exc.value)


@pytest.mark.asyncio
async def test_timeout_is_not_no_result(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")

    def handler(request):
        raise httpx.TimeoutException("timed out")

    async with client_with(handler) as client:
        with pytest.raises(AmapTimeout):
            await amap_poi_search(keywords="雷峰塔", client=client)


def test_key_alias_and_missing_key(monkeypatch):
    monkeypatch.delenv("AMAP_MAPS_API_KEY", raising=False)
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "alias-key")
    assert amap_client.amap_api_key() == "alias-key"

    monkeypatch.delenv("AMAP_WEB_SERVICE_KEY", raising=False)
    monkeypatch.setenv("AMAP_MAPS_API_KEY", "legacy-key")
    assert amap_client.amap_api_key() == "legacy-key"

    monkeypatch.delenv("AMAP_MAPS_API_KEY", raising=False)
    monkeypatch.setattr(
        amap_client, "get_settings", lambda: type("S", (), {"mcp_servers": {}})()
    )
    with pytest.raises(AmapNotConfigured):
        amap_client.amap_api_key()


@pytest.mark.asyncio
async def test_tool_wrapper_returns_not_configured_without_raising(monkeypatch):
    async def missing(**kwargs):
        raise AmapNotConfigured("配置缺失")

    monkeypatch.setattr(builtin_tools, "amap_poi_search", missing)
    result = await builtin_tools.amap_place_search_tool(query="雷峰塔")
    assert result["success"] is False
    assert result["error_code"] == "not_configured"
    assert result["configured"] is False


@pytest.mark.asyncio
async def test_tool_wrapper_maps_query_to_service_keywords(monkeypatch):
    seen = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return {"success": True, "places": []}

    monkeypatch.setattr(builtin_tools, "amap_poi_search", fake)
    result = await builtin_tools.amap_place_search_tool(query="雷峰塔", city="杭州")
    assert result["success"] is True
    assert seen["keywords"] == "雷峰塔"
    assert "query" not in seen
