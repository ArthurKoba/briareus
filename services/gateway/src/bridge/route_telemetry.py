"""Bounded transport-only request observations; no paths, query, tokens or bodies."""

from __future__ import annotations

import logging
from time import monotonic
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .single_origin import MCP_ENDPOINTS

_LOG = logging.getLogger("uvicorn.error")
_SUPPORTED = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})


def _route(path: str) -> tuple[str, str]:
    if path in {"/", "/robots.txt", "/sitemap.xml"}:
        return "landing", "panel-ui"
    if path in {"/panel", "/panel/"}:
        return "panel-shell", "panel-ui"
    if path.startswith("/panel/assets/"):
        return "panel-asset", "panel-ui"
    if path == "/api" or path.startswith("/api/"):
        return "api", "panel-api"
    if path in MCP_ENDPOINTS.values():
        return "mcp-admission", "authorization"
    if path.startswith("/hands/"):
        return "hands-disabled", "deny"
    return "other", "deny"


def _bucket(n: int, first: int, second: int) -> str:
    return "small" if n <= first else "medium" if n <= second else "large"


class RouteTelemetry:
    """ASGI status/latency/bytes measurement with constant-size route labels."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        route, target = _route(str(scope.get("path", "")))
        candidate_method: Any = scope.get("method", "")
        method = candidate_method if candidate_method in _SUPPORTED else "OTHER"
        started = monotonic()
        status = 500
        output_bytes = 0

        async def counted_send(message: Message) -> None:
            nonlocal status, output_bytes
            if message.get("type") == "http.response.start":
                status = int(message["status"])
            elif message.get("type") == "http.response.body":
                body = message.get("body", b"")
                if isinstance(body, bytes):
                    output_bytes += len(body)
            await send(message)

        try:
            await self.app(scope, receive, counted_send)
        finally:
            elapsed_ms = int((monotonic() - started) * 1000)
            _LOG.info(
                "gateway_route route=%s target=%s method=%s status=%d latency=%s bytes=%s",
                route,
                target,
                method,
                status,
                _bucket(elapsed_ms, 100, 1000),
                _bucket(output_bytes, 1024, 102400),
            )
