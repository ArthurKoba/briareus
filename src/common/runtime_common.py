from __future__ import annotations

from fastmcp import FastMCP
from starlette.applications import Starlette

from .management_client import ManagementClient
from .observability import announce_runtime_started, build_observability
from .settings import ManagementClientSettings, PrivateRuntimeSettings
from .tool_observability import ToolObservabilityMiddleware


def management_client(settings: ManagementClientSettings) -> ManagementClient:
    return ManagementClient(settings)


def build_private_mcp(
    name: str,
    management: ManagementClient | None = None,
    *,
    observability_scope: str | None = None,
) -> FastMCP:
    scope = observability_scope or name
    sink = build_observability(scope, management=management)
    announce_runtime_started(sink, scope)
    return FastMCP(name, middleware=[ToolObservabilityMiddleware(scope, sink)])


def private_http_app(mcp: FastMCP, settings: PrivateRuntimeSettings) -> Starlette:
    return mcp.http_app(
        path="/mcp",
        allowed_hosts=list(settings.http.allowed_hosts),
        allowed_origins=list(settings.http.allowed_origins),
    )
