from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from common.models import JsonObject


@dataclass
class CachedSnapshot:
    key: str
    category: str
    parameters: JsonObject = field(default_factory=dict)
    payload: JsonObject = field(default_factory=dict)
    refresh_after_seconds: int = 300
    status: str = "pending"
    updated_at: datetime | None = None
    attempted_at: datetime | None = None
    error_type: str = ""
    error_message: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def age_seconds(self, now: datetime | None = None) -> float | None:
        if self.updated_at is None:
            return None
        current = now or datetime.now(UTC)
        updated = self.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        return max(0.0, (current - updated).total_seconds())

    def stale(self, now: datetime | None = None) -> bool:
        age = self.age_seconds(now)
        return age is None or age >= self.refresh_after_seconds
