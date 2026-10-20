from travel_agent.agents.destination_researcher.node import (
    _restaurants_from_amap_places,
)


def test_amap_place_results_become_dining_identity_records():
    places = [
        {
            "amap_poi_id": "B001",
            "name": "楼外楼",
            "address": "西湖区孤山路",
            "typecode": "050101",
            "latitude": 30.2527,
            "longitude": 120.1361,
        },
        {
            "amap_poi_id": "B002",
            "name": "不是餐厅",
            "address": "西湖区",
            "typecode": "110000",
            "latitude": 30.25,
            "longitude": 120.13,
        },
    ]
    records = _restaurants_from_amap_places(places)
    assert len(records) == 1
    record = records[0]
    assert record["provider"] == "amap"
    assert record["place_id"].startswith("amap:poi:")
    assert record["name"] == "楼外楼"
    assert record["latitude"] == 30.2527
    assert record["longitude"] == 120.1361
    assert "餐饮服务" in record["provider_place_type"]
