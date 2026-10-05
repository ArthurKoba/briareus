from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

import valkey

from common.cache import SharedCache
from common.settings import ValkeySettings

logger = logging.getLogger(__name__)


class AccessEventPublisher:
    """Best-effort access lifecycle fanout onto the admin realtime channel."""

    def __init__(self, cache: SharedCache, settings: ValkeySettings) -> None:
        self.cache = cache
        self.channel = cache.key("realtime", "fanout")
        self.source_id = f"access:{uuid.uuid4().hex}"
        self._redis = valkey.Valkey.from_url(
            settings.url,
            decode_responses=True,
            socket_connect_timeout=settings.socket_connect_timeout_seconds,
            socket_timeout=settings.socket_timeout_seconds,
            health_check_interval=30,
        )

    async def close(self) -> None:
        await asyncio.to_thread(self._redis.close)

    async def publish(self, event_type: str, data: object) -> None:
        envelope = {
            "version": 1,
            "topic": "access.sessions",
            "type": event_type,
            "event_id": uuid.uuid4().hex,
            "occurred_at": datetime.now(UTC).isoformat(),
            "data": data,
        }
        await asyncio.to_thread(
            self.cache.set_json,
            self.cache.key("realtime", "snapshot", "access.sessions"),
            envelope,
            ttl_seconds=60,
        )
        encoded = json.dumps(
            {"source": self.source_id, "event": envelope},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            await asyncio.to_thread(self._redis.publish, self.channel, encoded)
        except valkey.exceptions.ValkeyError:
            logger.warning("access realtime Valkey publish failed")
