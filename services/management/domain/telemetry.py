from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field

from common.models import StrictModel


class Invocation(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()), pattern=r"^[0-9a-f-]{36}$")
    request_id: str = ""
    module: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=256)
    account_id: str = ""
    provider: str = ""
    status: Literal["success", "error"]
    duration_ms: float = Field(ge=0)
    error_type: str = ""
    arguments_json: str = ""
    result_json: str = ""
    error_message: str = ""
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

class InvocationQuery(StrictModel):
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    cursor_at: datetime | None = None
    cursor_id: str = ""
    module: str = Field(default="", max_length=64)
    tool: str = Field(default="", max_length=256)
    provider: str = Field(default="", max_length=32)
    account_id: str = Field(default="", max_length=128)
    status: Literal["success", "error"] | None = None
    search: str = Field(default="", max_length=256)


class InvocationPage(StrictModel):
    events: list[Invocation]
    total: int = Field(ge=0)
    count: int = Field(ge=0)
    has_more: bool
    next_cursor_at: datetime | None = None
    next_cursor_id: str = ""
