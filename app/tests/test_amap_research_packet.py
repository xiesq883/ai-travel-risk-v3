from travel_agent.agents.research_packet_output import _successful_place_records
from travel_agent.services.amap_place_search import _amap_place_type_label


def test_amap_place_envelope_enters_authoritative_place_registry():
    envelope = {
        "tool_name": "amap_place_search",
        "status": "success",
        "audit_id": "audit-amap-1",
        "metadata": {"evidence_allowed": True},
        "sanitized_result": {
            "success": True,
            "provider": "amap",
            "places": [
                {
                    "place_id": "amap:B001",
                    "name": "灵隐寺",
                    "address": "西湖区法云弄1号",
                    "provider_place_type": "风景名胜·景点（amap typecode 110202）",
                    "provider_country_code": "CN",
                    "latitude": 30.2409,
                    "longitude": 120.1022,
                }
            ],
        },
    }
    records = _successful_place_records(
        [{"role": "tool", "content": envelope}]
    )
    assert "amap:B001" in records
    assert records["amap:B001"][0]["audit_id"] == "audit-amap-1"


def test_amap_type_labels_carry_admission_markers():
    assert "餐饮服务" in _amap_place_type_label("050101", "")
    assert "住宿服务" in _amap_place_type_label("100000", "")
    assert "风景名胜" in _amap_place_type_label("110202", "")
