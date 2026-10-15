"""Local elapsed-time cap for an already authenticated absolute owner lease.

Capturing a deadline never authenticates it. UTC expiry still applies, but
clock rollback cannot replenish an observed budget while a read awaits IO.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ._read_adapter import FilesMcpReadUnavailable


@dataclass(frozen=True, slots=True)
class ReadLeaseDeadline:
    expires_at: datetime
    _elapsed_deadline: float = field(repr=False)

    @classmethod
    def capture(
        cls, expires_at: datetime, *, maximum_seconds: float | None = None
    ) -> ReadLeaseDeadline:
        # Read elapsed time FIRST: time spent obtaining/validating the wall
        # timestamp must shorten, not extend, this local budget.
        started = time.monotonic()
        if not isinstance(expires_at, datetime) or expires_at.tzinfo is None:
            raise FilesMcpReadUnavailable("FILES_OWNER_DEADLINE_INVALID")
        remaining = (expires_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0 or (maximum_seconds is not None and remaining > maximum_seconds):
            raise FilesMcpReadUnavailable("FILES_OWNER_AUTHORITY_EXPIRED")
        return cls(expires_at, started + remaining)

    def check(self) -> None:
        if datetime.now(UTC) >= self.expires_at or time.monotonic() >= self._elapsed_deadline:
            raise FilesMcpReadUnavailable("FILES_OWNER_AUTHORITY_EXPIRED")
