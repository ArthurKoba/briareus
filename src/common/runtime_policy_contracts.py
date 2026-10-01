from __future__ import annotations

from pydantic import Field

from .models import StrictModel


class TerminalRuntimePolicy(StrictModel):
    max_exec_timeout_seconds: int = Field(300, ge=1, le=86_400)
    max_job_runtime_seconds: int = Field(3600, ge=1, le=604_800)
