from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from travel_agent.api.routes import risk as risk_route
from travel_agent.services.travel_risk_adapter import risk_input_from_bundle
from travel_agent.services.travel_risk_engine import TravelRiskEngine

NOW = datetime(2026, 10, 16, 4, tzinfo=timezone.utc)


def bundle_fixture():
    start = NOW + timedelta(days=1)
    leg = NS(
        transport_leg_id="train-1", route_status="ready", duration_minutes=120,
        departure_at=start, arrival_at=start + timedelta(hours=2),
        from_endpoint=NS(name="昆明站"), to_endpoint=NS(name="大理站"),
        lineage=NS(fact_assertion_ids=["fact-1"], source_record_ids=["source-1"]),
        segments=[NS(segment_id="s1", mode=NS(value="high_speed_rail"), arrival_at=start + timedelta(hours=2), departure_at=start, to_endpoint=NS(name="大理站"))],
    )
    visit = NS(item_id="visit-1", name="博物馆", duration_minutes=120, planned_start=start + timedelta(hours=1), planned_end=start + timedelta(hours=3))
    day = NS(day_id="d1", date=start.date(), destination_id="dali", theme="大理游览", timeline=[NS(entity_id="train-1", projection_role="departure"), NS(entity_id="visit-1", projection_role="full")])
    weather = NS(destination_id="dali", date=start.date(), data_kind="forecast", fact_assertion_ids=["fact-1"], precipitation_mm=0, precipitation_probability_pct=10, high_c=24, low_c=14, wind_speed_kph=10, condition_code=2)
    fact = NS(fact_assertion_id="fact-1", status="verified", expires_at=NOW + timedelta(hours=6), observed_at=NOW, source_links=[NS(source_record_id="source-1")])
    source = NS(source_record_id="source-1", lifecycle_status="active", title="测试来源")
    return NS(
        manifest=NS(bundle_id="bundle-1"),
        workspace=NS(itinerary=NS(title="云南测试行程", day_plans=[day], visit_stops=[visit], dining_stops=[], custom_blocks=[], transport_legs=[leg], cost_summary=NS(known_subtotal_cny=500, estimated_total_cny=650, budget_cap_cny=1000, coverage="complete"))),
        fact_snapshot=NS(fact_assertions=[fact], source_records=[source]),
        weather_snapshot=NS(days=[weather]),
    )


def test_adapter_reads_trip_totals_and_preserves_unmeasured_fields():
    bundle = bundle_fixture()
    original = deepcopy(bundle)
    result = risk_input_from_bundle(bundle, now=NOW)
    assert result.costs[0].amount_cny == 500
    assert result.costs[0].upper_cny == 650
    assert result.costs[0].basis == "estimate"
    day = result.days[0]
    assert day.active_minutes == 240
    assert day.walking_km is None and day.rest_minutes is None and day.outdoor_minutes is None
    assert day.transports[0].source_ids == ["source-1"]
    assert day.transports[0].route_status == "ready"
    assert day.weather.observed_at == NOW
    assert bundle == original


def test_adapter_detects_schedule_overlap_and_keeps_entity_trace():
    request = risk_input_from_bundle(bundle_fixture(), now=NOW)
    result = TravelRiskEngine().assess(request, assessed_at=NOW, input_origin="journeypilot", bundle_id="bundle-1")
    transport = next(d for d in result.dimensions if d.category == "transport")
    assert transport.level == "high"
    assert set(transport.findings[0].entity_ids) == {"train-1", "visit-1"}
    assert result.bundle_id == "bundle-1" and not result.data_complete


def test_overnight_leg_is_not_counted_again_on_arrival_day():
    bundle = bundle_fixture()
    arrival_day = deepcopy(bundle.workspace.itinerary.day_plans[0])
    arrival_day.day_id = "d2"
    arrival_day.date += timedelta(days=1)
    arrival_day.timeline = [NS(entity_id="train-1", projection_role="arrival")]
    bundle.workspace.itinerary.day_plans.append(arrival_day)
    result = risk_input_from_bundle(bundle, now=NOW)
    assert len(result.days[0].transports) == 1
    assert not result.days[1].transports
    assert result.days[1].active_minutes == 0


def test_expired_or_withdrawn_sources_cannot_be_marked_verified():
    bundle = bundle_fixture()
    bundle.fact_snapshot.fact_assertions[0].expires_at = NOW - timedelta(seconds=1)
    result = risk_input_from_bundle(bundle, now=NOW)
    assert result.days[0].weather.data_kind == "unavailable"
    assert result.days[0].transports[0].route_status == "estimated"
    bundle.fact_snapshot.fact_assertions[0].expires_at = None
    bundle.fact_snapshot.source_records[0].lifecycle_status = "withdrawn"
    result = risk_input_from_bundle(bundle, now=NOW)
    assert result.days[0].weather.data_kind == "unavailable"


def test_naive_timestamps_are_left_unverified_instead_of_crashing():
    bundle = bundle_fixture()
    leg = bundle.workspace.itinerary.transport_legs[0]
    leg.departure_at = leg.departure_at.replace(tzinfo=None)
    result = risk_input_from_bundle(bundle, now=NOW)
    assert result.days[0].transports[0].available_minutes is None


def test_trip_endpoint_checks_access_before_reading_bundle(monkeypatch):
    async def denied(run_id, **kwargs):
        raise HTTPException(status_code=403, detail="无权访问")

    def forbidden_store():
        raise AssertionError("Must not read bundle before access check")

    monkeypatch.setattr(risk_route, "_get_authorized_run", denied)
    monkeypatch.setattr(risk_route, "get_components", forbidden_store)
    app = FastAPI()
    app.include_router(risk_route.router)
    with TestClient(app) as client:
        assert client.get("/api/risk/trips/other-run").status_code == 403


def test_trip_endpoint_returns_missing_bundle_as_404(monkeypatch):
    async def authorized(run_id, **kwargs):
        return NS()

    class Store:
        async def get_current(self, run_id):
            return None

    monkeypatch.setattr(risk_route, "_get_authorized_run", authorized)
    monkeypatch.setattr(risk_route, "get_components", lambda: NS(delivery_bundle_store=Store()))
    app = FastAPI()
    app.include_router(risk_route.router)
    with TestClient(app) as client:
        response = client.get("/api/risk/trips/pending-run")
        assert response.status_code == 404
        assert "尚无" in response.json()["detail"]


def test_reassessment_keeps_imported_bundle_provenance():
    request = risk_input_from_bundle(bundle_fixture(), now=NOW)
    payload = request.model_dump(mode="json")
    original = deepcopy(payload)
    app = FastAPI()
    app.include_router(risk_route.router)
    with TestClient(app) as client:
        imported = client.post(
            "/api/risk/assess",
            params={"input_origin": "journeypilot", "bundle_id": "bundle-1"},
            json=payload,
        )
        assert imported.status_code == 200
        assert imported.json()["input_origin"] == "journeypilot"
        assert imported.json()["bundle_id"] == "bundle-1"
        manual = client.post("/api/risk/assess", json=payload)
        assert manual.status_code == 200
        assert manual.json()["input_origin"] == "manual"
        assert manual.json()["bundle_id"] is None
    assert payload == original
