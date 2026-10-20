from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from travel_agent.api.routes.risk import router
from travel_agent.entities.travel_risk import RiskAssessmentInput
from travel_agent.services.travel_risk_optimizer import TravelRiskOptimizer
from travel_agent.services.travel_risk_engine import TravelRiskEngine

# The forecast-freshness rule compares against real time when the HTTP endpoint
# is exercised.  A frozen "yesterday" made that test expire with the calendar,
# not with the code.
NOW = datetime.now(timezone.utc)


def complete_input():
    return {
        "title": "测试方案",
        "budget_cap_cny": 1000,
        "costs_complete": True,
        "costs": [{"item_id": "c1", "name": "整趟费用", "amount_cny": 500}],
        "days": [
            {
                "day_id": "d1",
                "date": (NOW + timedelta(days=1)).date().isoformat(),
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


def test_optimizer_preserves_original_and_reassesses_applied_schedule_changes():
    data = complete_input()
    day = data["days"][0]
    day.update(outdoor_minutes=120, walking_km=12, active_minutes=660, rest_minutes=15)
    day["weather"].update(precipitation_mm=25, precipitation_probability_pct=95)
    day["transports"][0].update(duration_minutes=180, available_minutes=120)
    day["connections"] = [{"name": "换乘", "available_minutes": 20, "required_minutes": 60}]
    request = RiskAssessmentInput.model_validate(data)
    original = deepcopy(request.model_dump())

    result = TravelRiskOptimizer().optimize(request, assessed_at=NOW)

    assert request.model_dump() == original
    assert result.original_input == request
    assert result.applied_count >= 5
    assert result.pending_count == 0
    optimized_day = result.optimized_input.days[0]
    assert optimized_day.outdoor_minutes == 0
    assert optimized_day.walking_km == 8
    assert optimized_day.active_minutes == 480
    assert optimized_day.rest_minutes == 45
    assert optimized_day.transports[0].available_minutes == 225
    assert optimized_day.connections[0].available_minutes == 75
    assert result.before.overall_level == "high"
    assert result.after.overall_level == "low"
    assert result.after.data_complete


def test_optimizer_does_not_invent_budget_reduction():
    data = complete_input()
    data["budget_cap_cny"] = 400
    request = RiskAssessmentInput.model_validate(data)

    result = TravelRiskOptimizer().optimize(request, assessed_at=NOW)

    budget = next(d for d in result.after.dimensions if d.category == "budget")
    assert budget.level == "high"
    assert result.pending_count >= 1
    budget_proposal = next(p for p in result.proposals if p.category == "budget")
    assert budget_proposal.status == "needs_confirmation"
    assert budget_proposal.after is None
    assert result.optimized_input.costs[0].amount_cny == 500


def test_optimize_endpoint_returns_before_after_loop_without_model_calls():
    app = FastAPI()
    app.include_router(router)
    data = complete_input()
    data["days"][0]["walking_km"] = 12

    with TestClient(app) as client:
        response = client.post(
            "/api/risk/optimize?input_origin=journeypilot&bundle_id=bundle-1",
            json=data,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["before"]["overall_level"] == "high"
    assert payload["after"]["overall_level"] == "low"
    assert payload["after"]["input_origin"] == "journeypilot"
    assert payload["after"]["bundle_id"] == "bundle-1"
    assert payload["optimized_input"]["days"][0]["walking_km"] == 8
    assert payload["proposals"][0]["status"] == "applied"


def test_optimizer_noop_for_complete_low_risk_plan():
    request = RiskAssessmentInput.model_validate(complete_input())
    result = TravelRiskOptimizer(TravelRiskEngine()).optimize(request, assessed_at=NOW)

    assert result.proposals == []
    assert result.applied_count == 0
    assert result.pending_count == 0
    assert result.before == result.after
