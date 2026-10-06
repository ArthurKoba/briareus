from __future__ import annotations

import json
import logging
import threading
import time
from typing import Protocol, cast

import valkey
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from .models import JsonValue, json_value
from .settings import ValkeySettings


class CacheBackend(Protocol):
    def key(self, *parts: str) -> str: ...

    def get_json(self, key: str) -> JsonValue | None: ...

    def set_json(self, key: str, value: object, *, ttl_seconds: int) -> bool: ...

    def delete(self, *keys: str) -> bool: ...


logger = logging.getLogger(__name__)
_TRACER = trace.get_tracer("mcp-bridge.valkey-cache")


class SharedCache:
    """Best-effort shared cache backed by private, ephemeral Valkey."""

    def __init__(self, settings: ValkeySettings | None = None) -> None:
        self.settings = settings or ValkeySettings()
        self._client = valkey.Valkey.from_url(
            self.settings.url,
            decode_responses=True,
            socket_connect_timeout=self.settings.socket_connect_timeout_seconds,
            socket_timeout=self.settings.socket_timeout_seconds,
            health_check_interval=30,
        )
        self._availability_lock = threading.Lock()
        self._disabled_until = 0.0

    def _available(self) -> bool:
        with self._availability_lock:
            return time.monotonic() >= self._disabled_until

    def _mark_failed(self, exc: Exception) -> None:
        now = time.monotonic()
        with self._availability_lock:
            should_log = now >= self._disabled_until
            self._disabled_until = now + self.settings.failure_backoff_seconds
        if should_log:
            logger.warning(
                "Valkey cache temporarily bypassed backoff_seconds=%.1f error=%s",
                self.settings.failure_backoff_seconds,
                type(exc).__name__,
            )

    def _mark_available(self) -> None:
        with self._availability_lock:
            self._disabled_until = 0.0

    def key(self, *parts: str) -> str:
        normalized = [self.settings.namespace.rstrip(":")]
        normalized.extend(part.strip().casefold() for part in parts if part.strip())
        return ":".join(normalized)

    def get_json(self, key: str) -> JsonValue | None:
        if not self._available():
            return None
        with _TRACER.start_as_current_span(
            "cache.get",
            kind=SpanKind.CLIENT,
            attributes={"cache.system": "valkey", "cache.namespace": self.settings.namespace},
        ) as span:
            try:
                raw = cast(str | None, self._client.get(key))
            except valkey.exceptions.ValkeyError as exc:
                span.record_exception(exc)
                span.set_attribute("cache.available", False)
                self._mark_failed(exc)
                return None
            self._mark_available()
            span.set_attribute("cache.available", True)
            span.set_attribute("cache.hit", raw is not None)
            if raw is None:
                return None
            try:
                decoded = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                self.delete(key)
                return None
            return json_value(decoded, context="Valkey cache value")

    def set_json(self, key: str, value: object, *, ttl_seconds: int) -> bool:
        if not self._available():
            return False
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with _TRACER.start_as_current_span(
            "cache.set",
            kind=SpanKind.CLIENT,
            attributes={
                "cache.system": "valkey",
                "cache.namespace": self.settings.namespace,
                "cache.ttl_seconds": ttl_seconds,
            },
        ) as span:
            try:
                self._client.set(key, encoded, ex=max(1, ttl_seconds))
            except valkey.exceptions.ValkeyError as exc:
                span.record_exception(exc)
                span.set_attribute("cache.available", False)
                self._mark_failed(exc)
                return False
            self._mark_available()
            span.set_attribute("cache.available", True)
            return True

    def delete(self, *keys: str) -> bool:
        values = tuple(key for key in keys if key)
        if not values:
            return True
        if not self._available():
            return False
        with _TRACER.start_as_current_span(
            "cache.delete",
            kind=SpanKind.CLIENT,
            attributes={"cache.system": "valkey", "cache.key_count": len(values)},
        ) as span:
            try:
                self._client.delete(*values)
            except valkey.exceptions.ValkeyError as exc:
                span.record_exception(exc)
                span.set_attribute("cache.available", False)
                self._mark_failed(exc)
                return False
            self._mark_available()
            span.set_attribute("cache.available", True)
            return True

    def ping(self) -> bool:
        try:
            result = bool(self._client.ping())
        except valkey.exceptions.ValkeyError as exc:
            self._mark_failed(exc)
            return False
        if result:
            self._mark_available()
        return result


class CacheKeys:
    def __init__(self, cache: CacheBackend) -> None:
        self.cache = cache

    def account(self, provider: str, selector: str) -> str:
        return self.cache.key("accounts", "resolved", provider, selector)

    def account_list(self, provider: str = "") -> str:
        return self.cache.key("accounts", "list", provider or "all")

    def terminal_policy(self) -> str:
        return self.cache.key("system", "runtime", "terminal")

    def mcp_policy(self) -> str:
        return self.cache.key("system", "runtime", "mcp")

    def github_policy(self) -> str:
        return self.cache.key("system", "runtime", "github")

    def gitlab_policy(self) -> str:
        return self.cache.key("system", "runtime", "gitlab")

    def browser_policy(self) -> str:
        return self.cache.key("system", "runtime", "browser")

    def management_config(self) -> str:
        return self.cache.key("system", "management", "config")

    def account_invalidation_keys(
        self,
        provider: str,
        *,
        account_id: str = "",
        alias: str = "",
    ) -> tuple[str, ...]:
        keys = [self.account_list(provider), self.account_list()]
        if account_id:
            keys.append(self.account(provider, account_id))
        if alias:
            keys.append(self.account(provider, alias))
        return tuple(dict.fromkeys(keys))
