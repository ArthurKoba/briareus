from __future__ import annotations

from pydantic import Field

from common.models import StrictModel


class AdminConfig(StrictModel):
    logging_enabled: bool = True
    logging_capture_payloads: bool = True
    logging_retention_days: int = Field(30, ge=1, le=3650)
    logging_max_records: int = Field(10_000, ge=100, le=1_000_000)
    maintenance_interval_minutes: int = Field(60, ge=1, le=1440)
