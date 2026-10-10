from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping

from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

from common.audit_payloads import redact_payload
from common.models import JsonObject, json_object
from common.observability import otlp_headers, telemetry_resource
from common.settings import ObservabilitySettings

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def _attribute_value(value: object) -> str | int | float | bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _frontend_attributes(event: Mapping[str, object]) -> dict[str, str | int | float | bool]:
    attributes: dict[str, str | int | float | bool] = {}
    for source, target in (
        ("id", "frontend.event.id"),
        ("name", "frontend.event.name"),
        ("occurredAt", "frontend.occurred_at"),
        ("route", "frontend.route"),
        ("durationMs", "frontend.duration_ms"),
    ):
        value = event.get(source)
        if value is not None:
            attributes[target] = _attribute_value(value)

    raw_attributes = event.get("attributes")
    if isinstance(raw_attributes, Mapping):
        for key, value in raw_attributes.items():
            normalized = str(key).strip().replace(" ", "_")
            if normalized:
                attributes[f"frontend.attribute.{normalized}"] = _attribute_value(value)
    return attributes


class FrontendTelemetryProxy:
    """Emit authenticated browser diagnostics through the shared OTLP transport."""

    def __init__(
        self,
        settings: ObservabilitySettings,
        *,
        service_name: str = "admin-ui",
    ) -> None:
        self.settings = settings
        self.service_name = service_name
        self._provider: LoggerProvider | None = None
        self._logger: logging.Logger | None = None

        if not settings.enabled:
            return

        provider = LoggerProvider(
            resource=telemetry_resource(
                settings,
                "frontend",
                service_name=service_name,
            )
        )
        provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(
                    endpoint=settings.signal_endpoint("logs"),
                    headers=otlp_headers(settings),
                    timeout=settings.timeout_seconds,
                )
            )
        )
        handler = LoggingHandler(level=logging.DEBUG, logger_provider=provider)
        logger = logging.Logger("briareus.frontend_telemetry", level=logging.INFO)
        logger.propagate = False
        logger.addHandler(handler)
        self._provider = provider
        self._logger = logger

    @property
    def enabled(self) -> bool:
        return self._provider is not None and self._logger is not None

    def start(self) -> None:
        """Kept for lifecycle symmetry; OTLP batching starts with the provider."""

    async def close(self) -> None:
        provider = self._provider
        self._provider = None
        self._logger = None
        if provider is None:
            return
        await asyncio.to_thread(provider.force_flush, timeout_millis=self.settings.timeout_ms)
        await asyncio.to_thread(provider.shutdown)

    def enqueue(self, events: list[object]) -> JsonObject:
        logger = self._logger
        if logger is None:
            return {
                "accepted": 0,
                "queued_batches": 0,
                "dropped_batches": len(events),
            }

        accepted = 0
        for raw_event in events:
            try:
                event = json_object(redact_payload(raw_event), context="frontend telemetry")
            except ValueError:
                continue
            name = str(event.get("name") or "frontend.event")
            level = _LEVELS.get(str(event.get("level") or "info").casefold(), logging.INFO)
            logger.log(
                level,
                name,
                extra=_frontend_attributes(event),
            )
            accepted += 1

        return {
            "accepted": accepted,
            "queued_batches": 0,
            "dropped_batches": len(events) - accepted,
        }
