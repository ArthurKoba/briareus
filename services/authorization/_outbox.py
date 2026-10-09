"""Durable SQL outbox claim/ack, independent of a particular message bus.

Publisher MUST return True only after durable consumer acknowledgement.
Valkey Pub/Sub delivery alone is NOT durable and must not acknowledge rows.
Not mounted or scheduled until C2 defines service identity/inbox semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase

from ._platform_persistence import OutboxRow


@dataclass(frozen=True, slots=True)
class ClaimedEvent:
    event_id: UUID
    claim_id: UUID
    event_name: str
    payload: dict[str, object]


class DurableEventSink(Protocol):
    async def publish(
        self,
        event_id: UUID,
        name: str,
        payload: dict[str, object],
    ) -> bool: ...


class OutboxDispatcher:
    def __init__(self, database: PlatformDatabase, sink: DurableEventSink) -> None:
        self.database = database
        self.sink = sink

    @staticmethod
    async def claim(
        tx: AsyncSession,
        *,
        limit: int = 64,
    ) -> list[ClaimedEvent]:
        if not 1 <= limit <= 256:
            raise ValueError("outbox batch limit must be between 1 and 256")
        now = datetime.now(UTC)
        rows = await tx.scalars(
            select(OutboxRow)
            .where(
                OutboxRow.published_at.is_(None),
                (OutboxRow.locked_until.is_(None) | (OutboxRow.locked_until <= now)),
            )
            .order_by(OutboxRow.created_at, OutboxRow.id)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        claimed = []
        for row in rows:
            claim_id = uuid4()
            row.claim_id = claim_id
            row.locked_until = now + timedelta(seconds=60)
            row.attempts += 1
            claimed.append(ClaimedEvent(row.id, claim_id, row.event_name, row.event_payload))
        return claimed

    @staticmethod
    async def finish(
        tx: AsyncSession,
        event: ClaimedEvent,
        *,
        acknowledged: bool,
    ) -> bool:
        row = await tx.scalar(
            select(OutboxRow).where(OutboxRow.id == event.event_id).with_for_update()
        )
        if row is None or row.claim_id != event.claim_id or row.published_at is not None:
            return False  # Lost lease/reclaimed: cannot count a durable ACK
        if acknowledged:
            row.published_at = datetime.now(UTC)
            row.locked_until = None
        else:
            # Retry with bounded backoff. No assertion of a durable delivery.
            delay = min(300, 2 ** min(row.attempts, 8))
            row.locked_until = datetime.now(UTC) + timedelta(seconds=delay)
        row.claim_id = None
        return acknowledged

    async def dispatch_once(self, *, limit: int = 64) -> int:
        async with self.database.transaction() as tx:
            batch = await self.claim(tx, limit=limit)
        acked = 0
        for event in batch:
            try:
                durable_ack = await self.sink.publish(
                    event.event_id, event.event_name, event.payload
                )
            except Exception:
                # Do not write provider/messaging exceptions containing secrets
                # into the durable outbox; retry is safe for idempotent consumers.
                durable_ack = False
            async with self.database.transaction() as tx:
                actually_acked = await self.finish(tx, event, acknowledged=durable_ack)
            if actually_acked:
                acked += 1
        return acked
