from __future__ import annotations

from fastmcp import FastMCP
from starlette.applications import Starlette

from .admin_api_client import AdminApiClient
from .observability import announce_runtime_started, build_observability
from .settings import AdminApiClientSettings, PrivateRuntimeSettings
from .tool_observability import ToolObservabilityMiddleware


def admin_api_client(settings: AdminApiClientSettings) -> AdminApiClient:
    return AdminApiClient(settings)


def build_private_mcp(
    name: str,
    admin_api: AdminApiClient | None = None,
    *,
    observability_scope: str | None = None,
) -> FastMCP:
    scope = observability_scope or name
    sink = build_observability(scope, admin_api=admin_api)
    announce_runtime_started(sink, scope)
    return FastMCP(name, middleware=[ToolObservabilityMiddleware(scope, sink)])


def private_http_app(mcp: FastMCP, settings: PrivateRuntimeSettings) -> Starlette:
    return mcp.http_app(
        path="/mcp",
        allowed_hosts=list(settings.http.allowed_hosts),
        allowed_origins=list(settings.http.allowed_origins),
    )
