from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from typing import Protocol

from .account_contracts import InvocationEvent
from .management_client import ManagementClient
from .settings import ObservabilitySettings

logger = logging.getLogger("mcp_bridge.observability")


class ObservabilitySink(Protocol):
    """Best-effort destination for runtime and MCP invocation observations."""

    def record_runtime_started(self, scope: str) -> None: ...

    def record_runtime_heartbeat(self, scope: str) -> None: ...

    def record_invocation(self, event: InvocationEvent) -> None: ...


class CompositeObservabilitySink:
    """Fan out one observation to independent sinks without coupling failures."""

    def __init__(self, sinks: Iterable[ObservabilitySink]) -> None:
        self.sinks = tuple(sinks)

    def record_runtime_started(self, scope: str) -> None:
        for sink in self.sinks:
            try:
                sink.record_runtime_started(scope)
            except Exception:
                continue

    def record_runtime_heartbeat(self, scope: str) -> None:
        for sink in self.sinks:
            try:
                sink.record_runtime_heartbeat(scope)
            except Exception:
                continue

    def record_invocation(self, event: InvocationEvent) -> None:
        for sink in self.sinks:
            try:
                sink.record_invocation(event)
            except Exception:
                continue


class ManagementAuditSink:
    """Persist redacted invocation history in Management for operator audit."""

    def __init__(self, management: ManagementClient) -> None:
        self.management = management

    def record_runtime_started(self, scope: str) -> None:
        del scope

    def record_runtime_heartbeat(self, scope: str) -> None:
        del scope

    def record_invocation(self, event: InvocationEvent) -> None:
        self.management.record_invocation(event)


def _parse_key_values(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item or "=" not in item:
            continue
        key, raw_value = item.split("=", 1)
        key = urllib.parse.unquote(key.strip())
        decoded = urllib.parse.unquote(raw_value.strip())
        if key:
            result[key] = decoded
    return result


def _otlp_value(value: object) -> dict[str, object]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": str(value)}


def _otlp_attributes(values: Mapping[str, object]) -> list[dict[str, object]]:
    return [
        {"key": key, "value": _otlp_value(value)}
        for key, value in sorted(values.items())
        if value is not None and value != ""
    ]


class OtlpHttpMetricsSink:
    """Export low-cardinality MCP/runtime metrics using OTLP/HTTP JSON."""

    def __init__(self, scope: str, settings: ObservabilitySettings) -> None:
        self.scope = scope
        self.settings = settings
        self.endpoint = settings.metrics_endpoint
        self.headers = _parse_key_values(settings.headers)
        self.resource_attributes = _parse_key_values(settings.resource_attributes)
        self.resource_attributes["service.name"] = settings.service_name
        self.resource_attributes["mcp.scope"] = scope
        self._success_logged = False
        self._last_error_log_at = 0.0
        logger.info(
            "OTLP metrics enabled scope=%s endpoint=%s service=%s",
            self.scope,
            self.endpoint,
            settings.service_name,
        )

    def _export(self, metrics: list[dict[str, object]]) -> None:
        if not self.endpoint or not metrics:
            return
        payload = {
            "resourceMetrics": [
                {
                    "resource": {
                        "attributes": _otlp_attributes(self.resource_attributes),
                    },
                    "scopeMetrics": [
                        {
                            "scope": {"name": f"mcp-bridge.{self.scope}"},
                            "metrics": metrics,
                        }
                    ],
                }
            ]
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "mcp-bridge-otlp/0.1",
            **self.headers,
        }
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.settings.timeout_seconds,
            ) as response:
                response.read(
                    min(
                        4096,
                        int(response.headers.get("Content-Length", "0") or 0),
                    )
                )
            if not self._success_logged:
                logger.info(
                    "OTLP export active scope=%s endpoint=%s",
                    self.scope,
                    self.endpoint,
                )
                self._success_logged = True
        except urllib.error.HTTPError as exc:
            self._log_export_error(f"HTTP {exc.code}: {exc.reason}")
        except urllib.error.URLError as exc:
            self._log_export_error(str(exc.reason))
        except OSError as exc:
            self._log_export_error(str(exc))

    def _log_export_error(self, detail: str) -> None:
        now = time.monotonic()
        if now - self._last_error_log_at < 60:
            return
        self._last_error_log_at = now
        logger.warning(
            "OTLP export failed scope=%s endpoint=%s error=%s",
            self.scope,
            self.endpoint,
            detail,
        )
    @staticmethod
    def _delta_counter(
        name: str,
        description: str,
        attributes: Mapping[str, object],
        now: str,
    ) -> dict[str, object]:
        return {
            "name": name,
            "description": description,
            "unit": "{event}",
            "sum": {
                "aggregationTemporality": 1,
                "isMonotonic": True,
                "dataPoints": [
                    {
                        "attributes": _otlp_attributes(attributes),
                        "startTimeUnixNano": now,
                        "timeUnixNano": now,
                        "asInt": "1",
                    }
                ],
            },
        }

    @staticmethod
    def _gauge(
        name: str,
        description: str,
        unit: str,
        value: float,
        attributes: Mapping[str, object],
        now: str,
    ) -> dict[str, object]:
        return {
            "name": name,
            "description": description,
            "unit": unit,
            "gauge": {
                "dataPoints": [
                    {
                        "attributes": _otlp_attributes(attributes),
                        "timeUnixNano": now,
                        "asDouble": value,
                    }
                ]
            },
        }

    @staticmethod
    def _histogram(
        name: str,
        description: str,
        unit: str,
        value: float,
        attributes: Mapping[str, object],
        now: str,
    ) -> dict[str, object]:
        bounds = [10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0]
        bucket_counts = [0] * (len(bounds) + 1)
        bucket_index = next(
            (index for index, bound in enumerate(bounds) if value <= bound),
            len(bounds),
        )
        bucket_counts[bucket_index] = 1
        return {
            "name": name,
            "description": description,
            "unit": unit,
            "histogram": {
                "aggregationTemporality": 1,
                "dataPoints": [
                    {
                        "attributes": _otlp_attributes(attributes),
                        "startTimeUnixNano": now,
                        "timeUnixNano": now,
                        "count": "1",
                        "sum": value,
                        "bucketCounts": [str(count) for count in bucket_counts],
                        "explicitBounds": bounds,
                        "min": value,
                        "max": value,
                    }
                ],
            },
        }

    def record_runtime_started(self, scope: str) -> None:
        now = str(time.time_ns())
        attrs = {"mcp.scope": scope}
        self._export(
            [
                self._delta_counter(
                    "mcp.runtime.started",
                    "Runtime process starts.",
                    attrs,
                    now,
                ),
                self._gauge(
                    "mcp.runtime.up",
                    "Runtime availability at observation time.",
                    "1",
                    1.0,
                    attrs,
                    now,
                ),
            ]
        )

    def record_runtime_heartbeat(self, scope: str) -> None:
        now = str(time.time_ns())
        self._export(
            [
                self._gauge(
                    "mcp.runtime.up",
                    "Runtime availability at observation time.",
                    "1",
                    1.0,
                    {"mcp.scope": scope},
                    now,
                )
            ]
        )

    def record_invocation(self, event: InvocationEvent) -> None:
        now = str(time.time_ns())
        attrs: dict[str, object] = {
            "mcp.scope": self.scope,
            "mcp.module": event.module,
            "mcp.tool": event.tool,
            "mcp.status": event.status,
        }
        if event.provider:
            attrs["mcp.provider"] = event.provider
        if event.error_type:
            attrs["error.type"] = event.error_type

        metrics = [
            self._delta_counter(
                "mcp.tool.calls",
                "MCP tool calls.",
                attrs,
                now,
            ),
            self._histogram(
                "mcp.tool.duration",
                "Observed MCP tool call duration.",
                "ms",
                event.duration_ms,
                attrs,
                now,
            ),
        ]
        if event.status == "error":
            metrics.append(
                self._delta_counter(
                    "mcp.tool.errors",
                    "MCP tool call errors.",
                    attrs,
                    now,
                )
            )
        self._export(metrics)


def build_observability(
    scope: str,
    *,
    management: ManagementClient | None = None,
    settings: ObservabilitySettings | None = None,
) -> CompositeObservabilitySink:
    configured = settings or ObservabilitySettings()
    sinks: list[ObservabilitySink] = []
    if management is not None:
        sinks.append(ManagementAuditSink(management))
    if configured.enabled:
        sinks.append(OtlpHttpMetricsSink(scope, configured))
    return CompositeObservabilitySink(sinks)


def announce_runtime_started(sink: ObservabilitySink, scope: str) -> None:
    """Start best-effort runtime lifecycle/heartbeat export in a daemon thread."""

    def run() -> None:
        sink.record_runtime_started(scope)
        while True:
            time.sleep(60)
            sink.record_runtime_heartbeat(scope)

    thread = threading.Thread(
        target=run,
        name=f"observability-{scope}-runtime",
        daemon=True,
    )
    thread.start()
