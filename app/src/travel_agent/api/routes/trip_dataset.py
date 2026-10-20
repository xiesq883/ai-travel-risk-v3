"""Read-only, versioned export of the generated trip as a per-day dataset."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response

from ...builders import get_components
from ...entities.trip_dataset import DATASET_SCHEMA_VERSION, TripDataset
from ...infrastructure.delivery_bundle_store import BundleContractSuperseded
from ...services.trip_dataset_builder import build_trip_dataset
from .trip_runs import _get_authorized_run, _raise_bundle_contract_superseded

router = APIRouter(prefix="/api/trip-runs", tags=["trip-dataset"])

_SUPPORTED_VERSIONS = {"v1", "1", "latest", DATASET_SCHEMA_VERSION}


def _check_version(version: str) -> None:
    if version not in _SUPPORTED_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_dataset_version",
                "message": "不支持的数据集版本",
                "supported": sorted(_SUPPORTED_VERSIONS),
            },
        )


async def _load_dataset(run_id: str, session_id: str | None, version: str) -> TripDataset:
    _check_version(version)
    run = await _get_authorized_run(run_id, session_id=session_id)
    try:
        bundle = await get_components().delivery_bundle_store.get_current(run_id)
    except BundleContractSuperseded as exc:
        _raise_bundle_contract_superseded(exc)
        raise AssertionError("unreachable")
    if bundle is None:
        raise HTTPException(
            status_code=404,
            detail="这趟行程尚无已完成的方案，无法导出结构化数据集。",
        )
    return build_trip_dataset(
        bundle,
        getattr(run, "controlled_trip_identity", None),
    )


@router.get("/{run_id}/dataset", response_model=TripDataset)
async def read_trip_dataset(
    run_id: str,
    response: Response,
    version: str = Query(default="v1"),
    session_id: str | None = Query(default=None),
) -> TripDataset:
    dataset = await _load_dataset(run_id, session_id, version)
    response.headers["X-JourneyPilot-Dataset-Schema"] = dataset.schema_version
    response.headers["X-JourneyPilot-Dataset-Id"] = dataset.dataset_id
    return dataset


@router.get("/{run_id}/dataset/export")
async def export_trip_dataset(
    run_id: str,
    version: str = Query(default="v1"),
    session_id: str | None = Query(default=None),
) -> Response:
    dataset = await _load_dataset(run_id, session_id, version)
    return Response(
        content=dataset.model_dump_json(indent=2),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="trip-dataset-{run_id}-{dataset.schema_version}.json"'
            ),
            "X-JourneyPilot-Dataset-Schema": dataset.schema_version,
            "X-JourneyPilot-Dataset-Id": dataset.dataset_id,
            "X-JourneyPilot-Bundle-Id": dataset.trip.bundle_id,
            "X-JourneyPilot-Workspace-Revision": str(dataset.trip.workspace_revision),
            "X-JourneyPilot-Fact-Revision": str(dataset.trip.fact_data_revision),
            "X-JourneyPilot-Weather-Revision": str(dataset.trip.weather_data_revision),
        },
    )


__all__ = ["router"]
