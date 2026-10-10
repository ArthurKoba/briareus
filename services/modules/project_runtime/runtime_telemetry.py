"""One owned OTel lifecycle for the Briareus Python Runtime ASGI services.

Actual exporter/settings implementations are Backend-owned `common` source.
Runtime alone owns how a service starts, heartbeats and flushes its sink.
Never expose collector bearer, service JWTs, UUIDs, request bodies, provider
credentials or high-cardinality resource identifiers in logs or attributes.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any

import mcp.types as mt
from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from starlette.applications import Starlette

from common.account_contracts import InvocationEvent
from common.observability import (
    CompositeObservabilitySink,
    OpenTelemetrySink,
    build_observability,
)
from common.settings import ObservabilitySettings

_LOG = logging.getLogger("briareus.runtime.telemetry")
_ALLOWED = frozenset({"gateway", "files", "terminal", "web", "svc", "infrastructure", "reverse"})
_HEARTBEAT_SECONDS = 60.0
# Explicitly closed metric dimensions. Unknown tool names never become tags.
_TOOL_FAMILIES = frozenset(
    {
        "access",
        "analysis",
        "bridge",
        "browser",
        "coolify",
        "devtools",
        "external",
        "file",
        "files",
        "ghidra",
        "git",
        "github",
        "gitlab",
        "job",
        "observability",
        "project",
        "resource",
        "runtime",
        "session",
        "terminal",
        "variable",
        "web",
    }
)


class _OnlySanitizedRuntimeLogs(logging.Filter):
    """Protect collector logs from generic old tool inputs and SDK errors.

    Backend's shared exporter currently installs a root LoggingHandler. A
    provider/HTTP exception or arbitrary Terminal argument can otherwise end
    up in the OTLP log body, even if MCP metrics are correctly redacted. Until
    A10 accepts a general safe log routing policy, forward only own bounded
    runtime lifecycle records. This filter does not change console handlers.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name in {"briareus.observability", "briareus.runtime.telemetry"}


class SafeRuntimeToolTelemetry(Middleware):
    """OTel metrics/spans with bounded static labels and NO payload capture.

    The historical generic MCP audit middleware may serialize tool arguments,
    result bodies and unaudited provider values. It must not receive Project
    bearer/delegation/collector secrets. Trace IDs are carried in the OTel
    context, never duplicated as high-cardinality metric dimensions.
    """

    def __init__(self, service: str, sink: CompositeObservabilitySink) -> None:
        self.service = service
        self.sink = sink

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        raw = context.message.name
        family = raw.partition("_")[0].partition(".")[0].casefold()
        tool = family if family in _TOOL_FAMILIES else "other"
        attributes: dict[str, object] = {"mcp.scope": self.service, "mcp.tool": tool}
        started = time.monotonic()
        failure: Exception | None = None
        result: ToolResult | None = None
        # Common OTel trace_span(record_exception=True) would put the original
        # exception.message (potentially credential-bearing) into exporter
        # events if a provider exception escaped the span context. Catch the
        # exception *inside*, record only bounded error TYPE, then propagate
        # it to FastMCP only AFTER the trace span has closed successfully.
        with self.sink.trace_span("briareus.runtime.tool", attributes):
            try:
                result = await call_next(context)
            except Exception as exc:
                failure = exc
                raw_error = type(exc).__name__
                error = (
                    raw_error if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", raw_error) else "Error"
                )
                self.sink.record_invocation(
                    InvocationEvent(
                        module=self.service,
                        tool=tool,
                        status="error",
                        duration_ms=(time.monotonic() - started) * 1000,
                        error_type=error,
                    ),
                    audit=False,
                )
            else:
                self.sink.record_invocation(
                    InvocationEvent(
                        module=self.service,
                        tool=tool,
                        status="success",
                        duration_ms=(time.monotonic() - started) * 1000,
                    ),
                    audit=False,
                )
        if failure is not None:
            raise failure
        assert result is not None
        return result


@dataclass(slots=True)
class RuntimeTelemetry:
    """Own a single exporter, not a second global tracer/meter provider."""

    service: str
    sink: CompositeObservabilitySink
    _started: bool = False

    @classmethod
    def construct(
        cls,
        service: str,
    ) -> RuntimeTelemetry:
        if service not in _ALLOWED:
            raise ValueError("unknown Briareus OTel service.name")
        settings = ObservabilitySettings()
        # Per-App literal identity is not another user-editable Team override.
        # Reject bad D4 composition rather than exporting service data under
        # a different product's resource name or a shared fake identity.
        if settings.service_name and settings.service_name != service:
            raise ValueError("OTEL_SERVICE_NAME conflicts with the Runtime service")
        # Do not create historical AdminApiAuditSink: that queue transports
        # rendered tool arguments/results and is NOT a protected MCP audit UoW.
        sink = build_observability(service, settings=settings)
        for channel in sink.sinks:
            if isinstance(channel, OpenTelemetrySink):
                channel.logging_handler.addFilter(_OnlySanitizedRuntimeLogs())
        return cls(service=service, sink=sink)

    async def _heartbeats(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=_HEARTBEAT_SECONDS)
            except TimeoutError:
                await asyncio.to_thread(self.sink.record_runtime_heartbeat, self.service)

    async def _shutdown(self) -> None:
        def close_all() -> None:
            # Existing shared CompositeObservabilitySink intentionally has no
            # close() method. Its Backend-owned concrete sinks do; never
            # install an additional exporter merely to flush these.
            for sink in reversed(self.sink.sinks):
                try:
                    if hasattr(sink, "shutdown"):
                        sink.shutdown()
                    elif hasattr(sink, "close"):
                        sink.close()
                except Exception:
                    _LOG.warning("Runtime telemetry shutdown failed service=%s", self.service)

        await asyncio.to_thread(close_all)

    def attach(self, app: Starlette) -> Starlette:
        """Wrap the EXISTING FastMCP lifespan, preserving provider cleanup."""
        original = app.router.lifespan_context

        @asynccontextmanager
        async def lifecycle(active: Starlette) -> AsyncIterator[Any]:
            # FastMCP may yield ASGI lifespan state (including its session
            # manager). Preserve it; dropping this mapping breaks tool calls
            # even though OTel startup metrics appeared to work.
            async with original(active) as original_state:
                if self._started:
                    raise RuntimeError("Runtime telemetry lifespan entered twice")
                self._started = True
                stop = asyncio.Event()
                task: asyncio.Task[None] | None = None
                try:
                    # `record_runtime_started` creates a counter, gauge,
                    # trace and redacted log and force-flushes all three.
                    # Startup reporting must not block the ASGI event loop.
                    await asyncio.to_thread(self.sink.record_runtime_started, self.service)
                    task = asyncio.create_task(self._heartbeats(stop))
                    yield original_state
                finally:
                    stop.set()
                    if task is not None:
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task
                    await self._shutdown()
                    self._started = False

        app.router.lifespan_context = lifecycle
        return app


def build_runtime_mcp(
    service: str,
    *,
    name: str | None = None,
) -> tuple[FastMCP, RuntimeTelemetry]:
    """One sink/provider per actual process, shared with MCP tool middleware."""
    owner = RuntimeTelemetry.construct(service)
    mcp = FastMCP(
        name or service,
        middleware=[SafeRuntimeToolTelemetry(service, owner.sink)],
    )
    return mcp, owner
