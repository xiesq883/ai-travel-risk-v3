import sys
from pathlib import Path
from types import SimpleNamespace as NS

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_trip_dataset import NOW, bundle_fixture, bundle_fixture_identity

from travel_agent.api.routes import risk as risk_route
from travel_agent.services.trip_dataset_builder import build_trip_dataset


def dataset_fixture():
    return build_trip_dataset(
        bundle_fixture(),
        bundle_fixture_identity(),
        now=NOW,
        settings=None,
    )


def client_with(monkeypatch, *, denied=False):
    dataset = dataset_fixture()

    async def fake_dataset(run_id, session_id):
        if denied:
            raise HTTPException(status_code=403, detail="无权访问")
        return NS(manifest=NS(bundle_id="bundle-ds-1")), dataset

    monkeypatch.setattr(risk_route, "_dataset_for_run", fake_dataset)
    app = FastAPI()
    app.include_router(risk_route.router)
    return TestClient(app), dataset


def test_import_endpoint_returns_dataset_without_assessment(monkeypatch):
    client, _ = client_with(monkeypatch)
    response = client.get("/api/risk/trips/trip-ds-1/dataset/import")
    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset"]["schema_version"] == "trip-dataset.v1"
    assert payload["input"]["budget_cap_cny"] is None
    assert payload["import_summary"]["bundle_id"] == "bundle-ds-1"
    assert payload["import_summary"]["day_count"] == 2


def test_assess_endpoint_needs_only_budget(monkeypatch):
    client, _ = client_with(monkeypatch)
    response = client.post(
        "/api/risk/trips/trip-ds-1/dataset/assess",
        json={"budget_cap_cny": 6000},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["input"]["budget_cap_cny"] == 6000
    assert payload["assessment"]["input_origin"] == "journeypilot"
    assert payload["assessment"]["bundle_id"] == "bundle-ds-1"
    assert len(payload["assessment"]["dimensions"]) == 4


def test_offline_dataset_can_be_previewed_and_assessed(monkeypatch):
    client, dataset = client_with(monkeypatch)
    preview = client.post(
        "/api/risk/dataset/import",
        json={"dataset": dataset.model_dump(mode="json"), "budget_cap_cny": None},
    )
    assert preview.status_code == 200
    assert preview.json()["input"]["budget_cap_cny"] is None

    assessed = client.post(
        "/api/risk/dataset/assess",
        json={"dataset": dataset.model_dump(mode="json"), "budget_cap_cny": 6000},
    )
    assert assessed.status_code == 200
    assert assessed.json()["assessment"]["bundle_id"] == dataset.trip.bundle_id
    assert assessed.json()["input"]["budget_cap_cny"] == 6000


def test_dataset_import_checks_access_before_bundle(monkeypatch):
    client, _ = client_with(monkeypatch, denied=True)
    assert client.get("/api/risk/trips/other/dataset/import").status_code == 403


def test_example_dataset_endpoint_is_marked_as_synthetic():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(risk_route.router)
    with TestClient(app) as client:
        response = client.get("/api/risk/dataset/example")
    assert response.status_code == 200
    assert response.json()["schema_version"] == "trip-dataset.v1"
