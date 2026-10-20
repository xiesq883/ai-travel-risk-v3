import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_trip_dataset import bundle_fixture, bundle_fixture_identity
from travel_agent.api.routes import trip_dataset as route


def make_client(monkeypatch, *, bundle=None, denied=False, identity=None):
    async def authorized(run_id, **kwargs):
        if denied:
            raise HTTPException(status_code=403, detail="无权访问")
        return NS(controlled_trip_identity=identity or bundle_fixture_identity())

    class Store:
        async def get_current(self, run_id):
            if denied:
                raise AssertionError("Must not read bundle before access check")
            return bundle

    monkeypatch.setattr(route, "_get_authorized_run", authorized)
    monkeypatch.setattr(
        route,
        "get_components",
        lambda: NS(delivery_bundle_store=Store()),
    )
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def test_dataset_endpoint_returns_versioned_payload(monkeypatch):
    client = make_client(monkeypatch, bundle=bundle_fixture())
    response = client.get("/api/trip-runs/trip-ds-1/dataset")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "trip-dataset.v1"
    assert len(payload["days"]) == 2
    assert payload["trip"]["bundle_id"] == "bundle-ds-1"
    assert response.headers["X-JourneyPilot-Dataset-Schema"] == "trip-dataset.v1"
    assert response.headers["X-JourneyPilot-Dataset-Id"].startswith("tds_")


def test_dataset_export_is_downloadable_json(monkeypatch):
    client = make_client(monkeypatch, bundle=bundle_fixture())
    response = client.get("/api/trip-runs/trip-ds-1/dataset/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["X-JourneyPilot-Fact-Revision"] == "7"
    assert json.loads(response.text)["dataset_id"].startswith("tds_")


def test_dataset_endpoint_reports_missing_bundle(monkeypatch):
    client = make_client(monkeypatch, bundle=None)
    response = client.get("/api/trip-runs/trip-ds-1/dataset")
    assert response.status_code == 404
    assert "尚无" in response.json()["detail"]


def test_dataset_endpoint_rejects_unknown_version(monkeypatch):
    client = make_client(monkeypatch, bundle=bundle_fixture())
    response = client.get("/api/trip-runs/trip-ds-1/dataset", params={"version": "v9"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unsupported_dataset_version"


def test_dataset_endpoint_checks_access_before_bundle(monkeypatch):
    client = make_client(monkeypatch, bundle=None, denied=True)
    assert client.get("/api/trip-runs/other/dataset").status_code == 403
