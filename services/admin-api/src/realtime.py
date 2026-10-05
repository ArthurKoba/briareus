from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, cast

import valkey
from pydantic import BaseModel, ConfigDict, Field

from common.cache import SharedCache
from common.models import JsonObject, JsonValue, json_value
from common.settings import ValkeySettings

logger = logging.getLogger(__name__)
REALTIME_VERSION: Final[int] = 1
REALTIME_TOPICS: Final[frozenset[str]] = frozenset(
    {
        "mcp.calls",
        "system.metrics",
        "system.notifications",
        "browser.runtime",
        "admin.events",
        "access.sessions",
    }
)


class RealtimeEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = REALTIME_VERSION
    topic: str
    type: str
    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: JsonValue


@dataclass(eq=False)
class RealtimeSubscriber:
    queue: asyncio.Queue[JsonObject] = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    topics: set[str] = field(default_factory=set)


class RealtimeBus:
    """Process-local subscribers with best-effort Valkey fanout and snapshot cache."""

    def __init__(self, cache: SharedCache, settings: ValkeySettings) -> None:
        self.cache = cache
        self.settings = settings
        self.channel = cache.key("realtime", "fanout")
        self.source_id = uuid.uuid4().hex
        self._subscribers: set[RealtimeSubscriber] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._redis = valkey.Valkey.from_url(
            settings.url,
            decode_responses=True,
            socket_connect_timeout=settings.socket_connect_timeout_seconds,
            socket_timeout=max(1.0, settings.socket_timeout_seconds),
            health_check_interval=30,
        )

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(
                self._listen(), name="admin-api-realtime-valkey"
            )

    async def close(self) -> None:
        task = self._listener_task
        self._listener_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def register(self) -> RealtimeSubscriber:
        subscriber = RealtimeSubscriber()
        self._subscribers.add(subscriber)
        return subscriber

    def unregister(self, subscriber: RealtimeSubscriber) -> None:
        self._subscribers.discard(subscriber)

    @staticmethod
    def validate_topic(topic: str) -> str:
        normalized = topic.strip()
        if normalized not in REALTIME_TOPICS:
            raise ValueError(f"unsupported realtime topic: {normalized}")
        return normalized

    def snapshot(self, topic: str) -> JsonValue | None:
        topic = self.validate_topic(topic)
        return self.cache.get_json(self.cache.key("realtime", "snapshot", topic))

    def _local_fanout(self, envelope: JsonObject) -> None:
        topic = str(envelope.get("topic") or "")
        for subscriber in tuple(self._subscribers):
            if topic not in subscriber.topics:
                continue
            if subscriber.queue.full():
                with suppress(asyncio.QueueEmpty):
                    subscriber.queue.get_nowait()
            with suppress(asyncio.QueueFull):
                subscriber.queue.put_nowait(envelope)

    def publish_sync(self, topic: str, event_type: str, data: object) -> JsonObject:
        topic = self.validate_topic(topic)
        envelope = RealtimeEnvelope(topic=topic, type=event_type, data=json_value(data)).model_dump(
            mode="json"
        )
        payload = json_value(envelope, context="realtime envelope")
        assert isinstance(payload, dict)
        self.cache.set_json(
            self.cache.key("realtime", "snapshot", topic),
            payload,
            ttl_seconds=60,
        )
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._local_fanout, payload)
        try:
            self._redis.publish(
                self.channel,
                json.dumps({"source": self.source_id, "event": payload}, separators=(",", ":")),
            )
        except valkey.exceptions.ValkeyError:
            logger.warning("realtime Valkey publish failed; using local fallback")
        return payload

    async def publish(self, topic: str, event_type: str, data: object) -> JsonObject:
        topic = self.validate_topic(topic)
        envelope = RealtimeEnvelope(topic=topic, type=event_type, data=json_value(data)).model_dump(
            mode="json"
        )
        payload = json_value(envelope, context="realtime envelope")
        assert isinstance(payload, dict)
        self.cache.set_json(
            self.cache.key("realtime", "snapshot", topic),
            payload,
            ttl_seconds=60,
        )
        self._local_fanout(payload)
        encoded = json.dumps({"source": self.source_id, "event": payload}, separators=(",", ":"))
        try:
            await asyncio.to_thread(self._redis.publish, self.channel, encoded)
        except valkey.exceptions.ValkeyError:
            logger.warning("realtime Valkey publish failed; using local fallback")
        return payload

    async def _listen(self) -> None:
        backoff = 0.5
        while True:
            pubsub = None
            try:
                pubsub = cast(Any, self._redis).pubsub(ignore_subscribe_messages=True)
                await asyncio.to_thread(pubsub.subscribe, self.channel)
                backoff = 0.5
                while True:
                    message = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
                    if not message:
                        await asyncio.sleep(0)
                        continue
                    raw = message.get("data") if isinstance(message, dict) else None
                    if not isinstance(raw, str):
                        continue
                    decoded = json.loads(raw)
                    if not isinstance(decoded, dict) or decoded.get("source") == self.source_id:
                        continue
                    event = decoded.get("event")
                    if isinstance(event, dict):
                        payload = json_value(event, context="realtime fanout")
                        if isinstance(payload, dict):
                            self._local_fanout(payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("realtime Valkey subscriber unavailable; retrying", exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(5.0, backoff * 2)
            finally:
                if pubsub is not None:
                    with suppress(Exception):
                        await asyncio.to_thread(pubsub.close)


async def periodic_metrics(bus: RealtimeBus, *, interval_seconds: float = 5.0) -> None:
    while True:
        await bus.publish(
            "system.metrics",
            "heartbeat",
            {"monotonic_seconds": time.monotonic(), "status": "ok"},
        )
        await asyncio.sleep(interval_seconds)
