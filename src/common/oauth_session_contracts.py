from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from .models import StrictModel

OAuthSessionStatus = Literal["active", "refresh_error", "invalid", "revoked"]


class OAuthSessionEvent(StrictModel):
    session_id: str = ""
    client_id: str
    client_name: str = ""
    resource: str = ""
    login: str = ""
    subject: str = ""
    scopes: list[str] = Field(default_factory=list)
    status: OAuthSessionStatus = "active"
    event: str
    access_jti: str = ""
    refresh_jti: str = ""
    access_expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error_type: str = ""
    error_message: str = ""
