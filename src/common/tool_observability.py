from __future__ import annotations

import asyncio
import time

import mcp.types as mt
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult

from .account_contracts import InvocationEvent
from .audit_payloads import render_error, render_payload
from .observability import ObservabilitySink


def management_audit_enabled(module: str, proxy_origin: str) -> bool:
    """Persist user-visible calls, but suppress Analysis->Ghidra proxy duplicates."""
    return not (
        module.strip().casefold() == "ghidra"
        and proxy_origin.strip().casefold() == "analysis"
    )


class ToolObservabilityMiddleware(Middleware):
    """Measure one MCP call once, then fan the observation out to configured sinks."""

    _MAX_PENDING_EVENTS = 128

    def __init__(self, module: str, sink: ObservabilitySink) -> None:
        self.module = module
        self.sink = sink
        self._tasks: set[asyncio.Task[None]] = set()

    @staticmethod
    def _account_id(context: MiddlewareContext[mt.CallToolRequestParams]) -> str:
        arguments = context.message.arguments or {}
        value = arguments.get("account_id")
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _request_id(context: MiddlewareContext[mt.CallToolRequestParams]) -> str:
        fastmcp_context = context.fastmcp_context
        if fastmcp_context is None or not fastmcp_context.request_context:
            return ""
        return str(fastmcp_context.request_id)

    async def _record(self, event: InvocationEvent, *, audit: bool) -> None:
        await asyncio.to_thread(self.sink.record_invocation, event, audit=audit)

    def _submit(self, event: InvocationEvent, *, audit: bool = True) -> None:
        if len(self._tasks) >= self._MAX_PENDING_EVENTS:
            return
        task = asyncio.create_task(self._record(event, audit=audit))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        started = time.monotonic()
        account_id = self._account_id(context)
        provider = self.module if self.module in {"github", "gitlab"} else ""
        request_id = self._request_id(context)
        arguments_json = render_payload(context.message.arguments or {})
        headers = get_http_headers()
        proxy_origin = headers.get("x-koba-proxy-origin", "").strip().casefold()
        audit = management_audit_enabled(self.module, proxy_origin)
        span_attributes: dict[str, object] = {
            "mcp.scope": self.module,
            "mcp.tool": context.message.name,
        }
        if provider:
            span_attributes["mcp.provider"] = provider
        if request_id:
            span_attributes["mcp.request.id"] = request_id
        if proxy_origin:
            span_attributes["mcp.proxy.origin"] = proxy_origin

        with self.sink.trace_span(
            f"mcp.tool.{context.message.name}",
            span_attributes,
        ):
            try:
                result = await call_next(context)
            except Exception as exc:
                event = InvocationEvent(
                    request_id=request_id,
                    module=self.module,
                    tool=context.message.name,
                    account_id=account_id,
                    provider=provider,
                    status="error",
                    duration_ms=(time.monotonic() - started) * 1000,
                    error_type=type(exc).__name__,
                    arguments_json=arguments_json,
                    error_message=render_error(exc),
                )
                self._submit(event, audit=audit)
                raise

            self._submit(
                InvocationEvent(
                    request_id=request_id,
                    module=self.module,
                    tool=context.message.name,
                    account_id=account_id,
                    provider=provider,
                    status="success",
                    duration_ms=(time.monotonic() - started) * 1000,
                    arguments_json=arguments_json,
                    result_json=render_payload(result),
                ),
                audit=audit,
            )
            return result
