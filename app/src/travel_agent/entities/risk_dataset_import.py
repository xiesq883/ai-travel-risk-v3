"""Read-only summary of one trip-dataset.v1 import into risk assessment."""

from __future__ import annotations

from datetime import date as Date
from typing import List, Optional

from pydantic import Field

from .contract_base import StrictModel
from .trip_dataset import AmountRange, DataSourceStatus


class DatasetImportSummary(StrictModel):
    dataset_id: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    bundle_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    destinations: List[str] = Field(default_factory=list)
    start_date: Date
    end_date: Date
    day_count: int = Field(ge=1)
    budget_cap_cny: Optional[float] = Field(default=None, ge=0)
    estimated_total: AmountRange = Field(default_factory=AmountRange)
    cost_coverage: str = "unknown"
    priced_cost_count: int = Field(default=0, ge=0)
    unknown_cost_count: int = Field(default=0, ge=0)
    estimated_fields: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    source_count: int = Field(default=0, ge=0)
    data_sources: List[DataSourceStatus] = Field(default_factory=list)


__all__ = ["DatasetImportSummary"]
