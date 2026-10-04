from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class OAuthSession:
    id: str
    client_id: str
    client_name: str = ""
    resource: str = ""
    login: str = ""
    subject: str = ""
    scopes: list[str] = field(default_factory=list)
    status: str = "active"
    last_event: str = ""
    access_jti: str = ""
    refresh_jti: str = ""
    previous_refresh_jti: str = ""
    access_expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None
    last_used_at: datetime | None = None
    last_refresh_at: datetime | None = None
    revoked_at: datetime | None = None
    error_type: str = ""
    error_message: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
