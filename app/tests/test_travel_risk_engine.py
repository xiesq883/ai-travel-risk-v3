from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from travel_agent.api.routes.risk import router
from travel_agent.entities.delivery_bundle import (
    EntityRef,
    WeatherDayContext,
    WeatherSensitivity,
)
from travel_agent.entities.travel_risk import RiskAssessmentInput
from travel_agent.services.travel_risk_engine import TravelRiskEngine
from travel_agent.services.weather_impact_engine import WeatherImpactEngine

NOW = datetime(2026, 10, 16, 4, tzinfo=timezone.utc)


def complete_input():
    return {
        "title": "测试方案",
        "budget_cap_cny": 1000,
        "costs_complete": True,
        "costs": [{"item_id": "c1", "name": "整趟费用", "amount_cny": 500}],
        "days": [
            {
                "day_id": "d1",
                "date": "2026-10-17",
                "destination": "昆明",
                "outdoor_minutes": 120,
                "active_minutes": 360,
                "walking_km": 4,
                "rest_minutes": 60,
                "transport_complete": True,
                "transports": [
                    {
                        "item_id": "t1",
                        "name": "公交",
                        "route_status": "ready",
                        "duration_minutes": 30,
                        "available_minutes": 60,
                    }
                ],
                "weather": {
                    "data_kind": "forecast",
                    "observed_at": NOW.isoformat(),
                    "high_c": 24,
                    "low_c": 14,
                    "precipitation_mm": 0,
                    "precipitation_probability_pct": 10,
                    "wind_speed_kph": 10,
                    "condition_code": 2,
                },
            }
        ],
    }


def test_explanation_contract_for_every_dimension_and_triggered_rule():
    data = complete_input()
    data["budget_cap_cny"] = 400
    day = data["days"][0]
    day.update(walking_km=12, active_minutes=660, rest_minutes=15)
    day["transports"][0]["duration_minutes"] = 180
    day["connections"] = [
        {"name": "换乘", "available_minutes": 20, "required_minutes": 60}
    ]
    day["weather"].update(
        precipitation_mm=25,
        precipitation_probability_pct=95,
        high_c=40,
        low_c=-10,
        wind_speed_kph=45,
        condition_code=95,
    )
    report = assess(data)
    assert report.engine_version == "travel-risk.v2"
    rules = set()
    for dim in report.dimensions:
        assert dim.explanation.risk_level == dim.level
        for finding in dim.findings:
            chain = finding.explanation
            rules.add(finding.rule_id)
            assert chain.risk_level == finding.level
            assert chain.data and chain.calculation and chain.rule and chain.explanation
            assert all(
                item.field and item.label and item.source_label for item in chain.data
            )
    assert rules == {
        "weather.rain",
        "weather.heat",
        "weather.cold",
        "weather.wind",
        "weather.thunderstorm",
        "budget.cap",
        "transport.window",
        "transport.connection",
        "fatigue.walking_km",
        "fatigue.active_minutes",
        "fatigue.rest",
    }
    # JSON export round-trips the exact evidence and trace, with no model call.
    assert type(report).model_validate_json(report.model_dump_json()) == report


def test_budget_chain_explains_range_sum_not_actual_spending():
    data = complete_input()
    data["costs"] = [
        {
            "item_id": "train",
            "name": "交通",
            "amount_cny": 500,
            "upper_cny": 700,
            "source_ids": ["quote-1"],
        },
        {"item_id": "hotel", "name": "住宿", "amount_cny": 400},
    ]
    chain = dimension(data, "budget").findings[0].explanation
    assert [c.result for c in chain.calculation] == [900, 1100, 110, -100]
    assert chain.data[2].source_ids == ["quote-1"]
    assert "不表示已实际花费" in chain.explanation
    assert "500.0 + 400.0" in chain.calculation[0].expression


@pytest.mark.parametrize(
    "amount,expected",
    [(899.999999, "low"), (900, "medium"), (1000, "medium"), (1000.000001, "high")],
)
def test_budget_chain_retains_unrounded_boundary_inputs(amount, expected):
    data = complete_input()
    data["costs"][0]["amount_cny"] = amount
    dim = dimension(data, "budget")
    assert dim.explanation.risk_level == expected
    assert str(amount) in dim.explanation.calculation[0].expression
    assert dim.explanation.data[2].value == amount


def test_weather_or_branch_and_missing_value_remain_visible_in_chain():
    data = complete_input()
    data["days"][0]["weather"].update(
        precipitation_mm=None,
        precipitation_probability_pct=95,
        source_label="手动天气",
        source_ids=["weather-1"],
    )
    dim = dimension(data, "weather")
    chain = dim.findings[0].explanation
    assert dim.level == "high" and dim.coverage == "partial"
    assert chain.data[1].value is None
    assert chain.data[2].source_ids == ["weather-1"]
    assert chain.data[2].observed_at == NOW
    assert chain.calculation[1].result == "未知，未按 0 处理"
    assert chain.calculation[2].result == "命中"
    assert "≥90%" in chain.rule


def test_expired_weather_chain_shows_age_and_blocking_reason():
    data = complete_input()
    data["days"][0]["weather"].update(
        observed_at=(NOW - timedelta(hours=25)).isoformat(), precipitation_mm=50
    )
    dim = dimension(data, "weather")
    assert dim.level == "unknown" and not dim.findings
    assert dim.explanation.calculation[0].result == 25
    assert any(
        "不可采用" in str(c.result) and "24 小时" in str(c.result)
        for c in dim.explanation.calculation
    )
    assert "资料不足" in dim.explanation.explanation


def test_transport_chain_shows_negative_window_and_buffer_deficit():
    data = complete_input()
    day = data["days"][0]
    day["transports"][0].update(
        duration_minutes=180, available_minutes=120, route_status="estimated"
    )
    day["connections"] = [
        {"name": "换乘", "available_minutes": 60, "required_minutes": 60}
    ]
    dim = dimension(data, "transport")
    assert dim.findings[0].explanation.calculation[0].result == -60
    assert "估算" in dim.findings[0].explanation.explanation
    chain = dim.findings[1].explanation
    assert chain.risk_level == "medium"
    assert [c.result for c in chain.calculation] == [0, 75]
    assert "还差 15" in chain.explanation
    assert chain.data[0].field.endswith("connections.0.available_minutes")


def test_fatigue_chain_uses_custom_limit_and_converts_minutes():
    data = complete_input()
    data["limits"] = {
        "max_daily_walking_km": 4,
        "max_daily_active_hours": 4,
        "min_daily_rest_minutes": 90,
    }
    day = data["days"][0]
    day.update(walking_km=5, active_minutes=360, rest_minutes=60)
    findings = dimension(data, "fatigue").findings
    assert [c.result for c in findings[0].explanation.calculation] == [5, 1, 125]
    assert findings[0].explanation.risk_level == "medium"  # exactly 125%, not above
    assert [c.result for c in findings[1].explanation.calculation] == [6, 2, 150]
    assert findings[1].explanation.data[1].field == "limits.max_daily_active_hours"
    assert findings[2].explanation.calculation[0].result == -30


def test_missing_and_passed_dimensions_both_have_explanation_chains():
    missing = assess({"days": [{"day_id": "d1", "date": "2026-10-17"}]})
    for dim in missing.dimensions:
        assert dim.explanation.risk_level == "unknown"
        assert any(item.value is None for item in dim.explanation.data)
        assert "资料不足" in dim.explanation.explanation
    for dim in assess(complete_input()).dimensions:
        assert dim.explanation.risk_level == "low"
        assert dim.explanation.calculation and dim.explanation.rule


def test_demo_labels_cover_all_evidence_without_mutating_input():
    request = RiskAssessmentInput.model_validate(
        {**complete_input(), "is_example": True}
    )
    before = request.model_dump()
    report = TravelRiskEngine().assess(request, assessed_at=NOW)
    assert request.model_dump() == before
    assert all(
        item.source_label.startswith("演示数据")
        for dim in report.dimensions
        for item in dim.explanation.data
    )


def assess(data):
    return TravelRiskEngine().assess(
        RiskAssessmentInput.model_validate(data), assessed_at=NOW
    )


def dimension(data, category):
    return next(d for d in assess(data).dimensions if d.category == category)


def test_exactly_four_dimensions_and_no_aggregate_numeric_score():
    result = assess(complete_input())
    assert [d.category for d in result.dimensions] == [
        "weather",
        "budget",
        "transport",
        "fatigue",
    ]
    assert result.overall_level == "low" and result.data_complete
    assert "score" not in result.model_dump()


def test_missing_inputs_are_never_green():
    result = assess({"days": [{"day_id": "d1", "date": "2026-10-17"}]})
    assert result.overall_level == "unknown"
    assert not result.data_complete
    assert all(d.level == "unknown" and d.missing_data for d in result.dimensions)


@pytest.mark.parametrize(
    "amount,expected",
    [(899.99, "low"), (900, "medium"), (1000, "medium"), (1000.01, "high")],
)
def test_budget_boundaries(amount, expected):
    data = complete_input()
    data["costs"][0]["amount_cny"] = amount
    assert dimension(data, "budget").level == expected


def test_budget_range_and_missing_prices_do_not_understate_overspend():
    data = complete_input()
    data["costs"][0].update(amount_cny=800, upper_cny=1200)
    data["costs"].append({"item_id": "unknown", "name": "机票"})
    data["costs_complete"] = False
    result = dimension(data, "budget")
    assert result.level == "high" and result.coverage == "partial"
    assert result.metrics["remaining_from_upper_cny"] == -200
    assert any("机票" in text for text in result.missing_data)


def test_budget_partial_below_cap_is_unknown_and_explicit_free_cost_is_valid():
    data = complete_input()
    data["costs_complete"] = False
    assert dimension(data, "budget").level == "unknown"
    data["costs_complete"] = True
    data["costs"][0]["amount_cny"] = 0
    assert dimension(data, "budget").level == "low"
    data["costs"] = []
    assert dimension(data, "budget").level == "unknown"


def test_money_is_summed_without_binary_rounding_artifacts():
    data = complete_input()
    data["costs"] = [
        {"item_id": str(i), "name": "费用", "amount_cny": 0.1} for i in range(3)
    ]
    assert dimension(data, "budget").metrics["recorded_min_cny"] == 0.3


@pytest.mark.parametrize(
    "field,value",
    [("amount_cny", -1), ("amount_cny", float("nan")), ("upper_cny", 100)],
)
def test_invalid_money_is_rejected(field, value):
    data = complete_input()
    data["costs"][0][field] = value
    with pytest.raises(ValidationError):
        RiskAssessmentInput.model_validate(data)


def test_rain_uses_shared_weather_rules_with_input_lineage():
    data = complete_input()
    data["days"][0]["weather"].update(
        precipitation_mm=25,
        precipitation_probability_pct=95,
        source_ids=["source-weather"],
    )
    result = dimension(data, "weather")
    assert result.level == "high"
    assert result.findings[0].day_id == "d1"
    assert result.findings[0].source_ids == ["source-weather"]
    assert result.findings[0].suggestion
    data["days"][0]["outdoor_minutes"] = 0
    assert dimension(data, "weather").level == "low"


@pytest.mark.parametrize(
    "patch",
    [
        {"data_kind": "seasonal_baseline"},
        {"observed_at": None},
        {"observed_at": (NOW - timedelta(hours=25)).isoformat()},
        {"observed_at": (NOW + timedelta(hours=1)).isoformat()},
        {"forecast_end_date": "2026-10-16"},
    ],
)
def test_unusable_weather_is_unknown_even_if_it_contains_heavy_rain(patch):
    data = complete_input()
    data["days"][0]["weather"].update(precipitation_mm=50, **patch)
    result = dimension(data, "weather")
    assert result.level == "unknown" and result.missing_data


@pytest.mark.parametrize("date", ["2026-10-15", "2026-10-23"])
def test_past_and_out_of_horizon_dates_are_unknown(date):
    data = complete_input()
    data["days"][0]["date"] = date
    assert dimension(data, "weather").level == "unknown"


def test_missing_weather_field_cannot_be_silently_zeroed():
    data = complete_input()
    data["days"][0]["weather"]["wind_speed_kph"] = None
    result = dimension(data, "weather")
    assert result.level == "unknown" and result.coverage == "partial"
    data["days"][0]["weather"]["condition_code"] = 95
    assert dimension(data, "weather").level == "high"


def test_crossing_midnight_does_not_extend_an_old_forecasts_horizon():
    data = complete_input()
    data["days"][0]["date"] = "2026-10-22"
    data["days"][0]["weather"]["observed_at"] = "2026-10-15T23:30:00+08:00"
    assert dimension(data, "weather").level == "unknown"


@pytest.mark.parametrize(
    "patch,rule,expected",
    [
        ({"high_c": 35}, "weather.heat", "medium"),
        ({"high_c": 40}, "weather.heat", "high"),
        ({"low_c": 0}, "weather.cold", "medium"),
        ({"low_c": -10}, "weather.cold", "high"),
        ({"wind_speed_kph": 30}, "weather.wind", "medium"),
        ({"wind_speed_kph": 45}, "weather.wind", "high"),
        ({"condition_code": 95}, "weather.thunderstorm", "high"),
        ({"condition_code": 73}, "weather.snow", "high"),
    ],
)
def test_shared_weather_thresholds_for_other_conditions(patch, rule, expected):
    data = complete_input()
    data["days"][0]["weather"].update(patch)
    result = dimension(data, "weather")
    assert result.level == expected
    assert any(f.rule_id == rule for f in result.findings)


@pytest.mark.parametrize(
    "walk,expected", [(8, "low"), (8.1, "medium"), (10, "medium"), (10.1, "high")]
)
def test_customizable_fatigue_threshold_boundaries(walk, expected):
    data = complete_input()
    data["days"][0]["walking_km"] = walk
    assert dimension(data, "fatigue").level == expected


def test_rest_unknown_is_different_from_zero_and_limits_change_the_result():
    data = complete_input()
    data["days"][0]["rest_minutes"] = None
    assert dimension(data, "fatigue").level == "unknown"
    data["days"][0]["rest_minutes"] = 0
    assert dimension(data, "fatigue").level == "medium"
    data["limits"] = {
        "max_daily_walking_km": 3,
        "max_daily_active_hours": 8,
        "min_daily_rest_minutes": 0,
    }
    assert dimension(data, "fatigue").level == "high"


@pytest.mark.parametrize(
    "gap,expected", [(-5, "high"), (59, "high"), (60, "medium"), (75, "low")]
)
def test_transfer_buffer_boundaries(gap, expected):
    data = complete_input()
    data["days"][0]["connections"] = [
        {"name": "换乘", "available_minutes": gap, "required_minutes": 60}
    ]
    assert dimension(data, "transport").level == expected


def test_transport_window_and_estimates_remain_distinct():
    data = complete_input()
    leg = data["days"][0]["transports"][0]
    leg.update(route_status="estimated", available_minutes=20)
    result = dimension(data, "transport")
    assert result.level == "high" and result.coverage == "partial"
    leg["available_minutes"] = 60
    assert dimension(data, "transport").level == "unknown"
    leg.update(route_status="ready", duration_minutes=None)
    assert dimension(data, "transport").level == "unknown"


def test_neither_engine_nor_shared_weather_rules_mutate_inputs():
    data = complete_input()
    copy = deepcopy(data)
    assess(data)
    assert data == copy
    day = WeatherDayContext(
        destination_id="kunming",
        date="2026-10-17",
        timezone="Asia/Shanghai",
        latitude=25,
        longitude=102,
        data_kind="forecast",
        precipitation_mm=25,
        precipitation_probability_pct=95,
        fact_assertion_ids=["real-fact"],
    )
    sensitivity = WeatherSensitivity(
        exposure="outdoor",
        rain_sensitivity="high",
        heat_sensitivity="high",
        cold_sensitivity="high",
        wind_sensitivity="high",
        requires_clear_visibility=False,
    )
    engine = WeatherImpactEngine()
    impacts = engine.evaluate(
        weather_day=day,
        sensitivity=sensitivity,
        target_ref=EntityRef(entity_type="visit_stop", entity_id="visit-1"),
    )
    assert [(i.condition_type, i.severity, i.action) for i in impacts] == [
        ("rain", "high", "replace")
    ]
    assert impacts[0].fact_assertion_ids == ["real-fact"]
    assert not engine.evaluate(
        weather_day=day.model_copy(update={"fact_assertion_ids": []}),
        sensitivity=sensitivity,
        target_ref=EntityRef(entity_type="visit_stop", entity_id="visit-1"),
    )


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_day",
        "duplicate_cost",
        "duplicate_transport",
        "unordered_dates",
        "naive_weather_time",
    ],
)
def test_invalid_identifiers_and_dates_are_rejected(change):
    data = complete_input()
    if change == "duplicate_day":
        data["days"].append(deepcopy(data["days"][0]))
    elif change == "duplicate_cost":
        data["costs"].append(deepcopy(data["costs"][0]))
    elif change == "duplicate_transport":
        data["days"][0]["transports"].append(deepcopy(data["days"][0]["transports"][0]))
    elif change == "unordered_dates":
        next_day = deepcopy(data["days"][0])
        next_day.update(day_id="d2", date="2026-10-16", transports=[])
        data["days"].append(next_day)
    else:
        data["days"][0]["weather"]["observed_at"] = "2026-10-16T12:00:00"
    with pytest.raises(ValidationError):
        RiskAssessmentInput.model_validate(data)


def test_api_works_without_model_keys_and_example_is_explicitly_labelled():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        example = client.get("/api/risk/example")
        assert example.status_code == 200
        data = example.json()
        assert data["is_example"] and len(data["days"]) == 5
        assert "演示" in data["days"][0]["weather"]["source_label"]
        result = client.post("/api/risk/assess", json=data)
        assert result.status_code == 200
        assert result.json()["overall_level"] == "high"
        assert all(d["level"] == "high" for d in result.json()["dimensions"])
        bad = deepcopy(data)
        bad["budget_cap_cny"] = -1
        assert client.post("/api/risk/assess", json=bad).status_code == 422
