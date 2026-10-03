from __future__ import annotations

import asyncio
import platform
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastmcp import FastMCP
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.providers.proxy import FastMCPProxy
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.routing import BaseRoute, WebSocketRoute
from starlette.websockets import WebSocket

from common.management_client import ManagementClient, ManagementClientError
from common.mcp_surfaces import (
    MCP_SURFACE_PATHS,
    resource_url,
    surface_base_url,
)
from common.models import JsonObject
from common.observability import announce_runtime_started, build_observability
from common.runtime_annotations import (
    DESTRUCTIVE_EXTERNAL,
    READ_EXTERNAL,
    READ_ONLY_LOCAL,
)
from common.runtime_policy_contracts import McpRuntimePolicy
from common.settings import (
    BridgeSettings,
    GatewayAuthSettings,
    ManagementClientSettings,
)
from common.websocket_proxy import relay_websocket

from . import __version__
from .auth_client import LocalAuthTokenVerifier
from .backend_router import BackendDescriptor, BackendRouter
from .backend_sessions import ProxyClientPool
from .models import BridgeBuildInfo, BridgeCapabilities, BridgePing
from .reverse_proxy import ReverseProxy

_STARTED_AT = datetime.now(UTC).isoformat()
_observability = build_observability("gateway")
announce_runtime_started(_observability, "gateway")
_AUTH_BACKEND_URL = "http://auth:8000"
_PROXY_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_AUTH_PROXY_PATHS = (
    "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration",
    "/authorize",
    "/token",
    "/register",
    "/revoke",
    "/auth/callback",
    "/consent",
)


async def _backend_timeout_seconds() -> float:
    try:
        policy = await asyncio.wait_for(
            asyncio.to_thread(_management.mcp_runtime_policy),
            timeout=1.0,
        )
    except (TimeoutError, ManagementClientError, ValueError):
        policy = McpRuntimePolicy()
    return float(policy.call_timeout_seconds)


def _proxy_target(name: str, target: str | FastMCP[Any]) -> FastMCP:
    pool = ProxyClientPool(
        target,
        name=name,
        timeout_provider=_backend_timeout_seconds,
        size=2,
    )
    return FastMCPProxy(
        client_factory=pool.acquire,
        name=f"{name}-backend",
        lifespan=pool.lifespan,
    )


def _proxy(name: str, url: str) -> FastMCP:
    return _proxy_target(name, url)


def _build_auth_reverse_proxy() -> ReverseProxy:
    return ReverseProxy(_AUTH_BACKEND_URL, backend_name="auth")


def _build_surface_auth(
    settings: GatewayAuthSettings,
    management: ManagementClient | None,
) -> dict[str, RemoteAuthProvider]:
    if not settings.enabled:
        return {}

    settings.validate_bootstrap()
    authorization_server = AnyHttpUrl(settings.public_base_url)
    result: dict[str, RemoteAuthProvider] = {}
    for surface in MCP_SURFACE_PATHS:
        resource = resource_url(settings.public_base_url, surface)
        verifier = LocalAuthTokenVerifier(settings, resource, management)
        result[surface] = RemoteAuthProvider(
            token_verifier=verifier,
            authorization_servers=[authorization_server],
            base_url=surface_base_url(settings.public_base_url, surface),
            scopes_supported=["read:user"],
            resource_name=f"Koba {surface.title()}",
        )
    return result


def _public_facade(
    name: str,
    backend_name: str,
    backend_url: str,
    auth_by_surface: dict[str, RemoteAuthProvider],
) -> FastMCP:
    surface = FastMCP(
        name,
        version=__version__,
        auth=auth_by_surface.get(name),
    )
    surface.mount(server=_proxy(backend_name, backend_url))
    return surface


_settings = BridgeSettings()
_auth_settings = GatewayAuthSettings()
_management_settings = ManagementClientSettings()
_BACKENDS = _settings.backends
_management = ManagementClient(_management_settings)
_auth_by_surface = _build_surface_auth(_auth_settings, _management)

_backend_router = BackendRouter(
    (
        BackendDescriptor(
            "github",
            _BACKENDS["github"],
            MCP_SURFACE_PATHS["github"],
            "GitHub repositories, pull requests, issues, Actions and reviews",
        ),
        BackendDescriptor(
            "gitlab",
            _BACKENDS["gitlab"],
            MCP_SURFACE_PATHS["gitlab"],
            "GitLab projects, repositories, merge requests, issues and CI",
        ),
        BackendDescriptor(
            "files",
            _BACKENDS["files"],
            MCP_SURFACE_PATHS["files"],
            "Persistent files, uploads, collections and object lifecycle",
        ),
        BackendDescriptor(
            "web",
            _BACKENDS["web"],
            MCP_SURFACE_PATHS["web"],
            "Web access through structured curl and persistent browser automation",
        ),
        BackendDescriptor(
            "analysis",
            _BACKENDS["analysis"],
            MCP_SURFACE_PATHS["analysis"],
            "General-purpose structured analysis surface",
        ),
        BackendDescriptor(
            "ghidra",
            _BACKENDS["ghidra"],
            "",
            "Private native analysis backend",
        ),
        BackendDescriptor(
            "terminal",
            _BACKENDS["terminal"],
            MCP_SURFACE_PATHS["terminal"],
            "Persistent Linux workspaces, commands and long-running jobs",
        ),
        BackendDescriptor(
            "observability",
            _BACKENDS["observability"],
            MCP_SURFACE_PATHS["observability"],
            "Unified read-only infrastructure state, logs, traces, metrics and deployments",
        ),
    ),
    timeout_provider=_backend_timeout_seconds,
)

mcp = FastMCP(
    "mcp-bridge",
    version=__version__,
    instructions=(
        "Universal MCP map and bridge. Dedicated backends are not automatically "
        "published on this root surface. Use bridge_backends to inspect availability, "
        "bridge_tools to fetch one backend tool catalog/signatures, and bridge_call "
        "to forward a call to a selected backend."
    ),
    auth=_auth_by_surface.get("root"),
)

github_surface = _public_facade(
    "github",
    "github",
    _BACKENDS["github"],
    _auth_by_surface,
)
gitlab_surface = _public_facade(
    "gitlab",
    "gitlab",
    _BACKENDS["gitlab"],
    _auth_by_surface,
)
files_surface = _public_facade(
    "files",
    "files",
    _BACKENDS["files"],
    _auth_by_surface,
)
web_surface = _public_facade(
    "web",
    "web",
    _BACKENDS["web"],
    _auth_by_surface,
)
analysis_surface = _public_facade(
    "analysis",
    "analysis",
    _BACKENDS["analysis"],
    _auth_by_surface,
)
terminal_surface = _public_facade(
    "terminal",
    "terminal",
    _BACKENDS["terminal"],
    _auth_by_surface,
)
observability_surface = _public_facade(
    "observability",
    "observability",
    _BACKENDS["observability"],
    _auth_by_surface,
)


@mcp.tool(title="Bridge ping", annotations=READ_ONLY_LOCAL)
def bridge_ping() -> JsonObject:
    return BridgePing(version=__version__, time=datetime.now(UTC).isoformat()).to_json()


@mcp.tool(title="Bridge build info", annotations=READ_ONLY_LOCAL)
def bridge_build_info() -> JsonObject:
    return BridgeBuildInfo(
        version=__version__,
        commit=_settings.build_sha,
        built_at=_settings.build_time,
        started_at=_STARTED_AT,
        python=platform.python_version(),
    ).to_json()


@mcp.tool(title="Bridge backends", annotations=READ_EXTERNAL)
async def bridge_backends() -> JsonObject:
    """List public/private bridge backends with live availability and tool counts."""
    return await _backend_router.describe()


@mcp.tool(title="Bridge backend tools", annotations=READ_EXTERNAL)
async def bridge_tools(backend: str, refresh: bool = False) -> JsonObject:
    """Fetch one backend tool catalog and signatures without publishing it at root."""
    return await _backend_router.tools(backend, refresh=refresh)


@mcp.tool(title="Bridge forward call", annotations=DESTRUCTIVE_EXTERNAL)
async def bridge_call(
    backend: str,
    tool_name: str,
    arguments: JsonObject | None = None,
) -> JsonObject:
    """Forward one tool call to a selected backend without adding bridge metadata."""
    return await _backend_router.call(backend, tool_name, arguments)


@mcp.tool(title="Bridge capabilities", annotations=READ_ONLY_LOCAL)
def bridge_capabilities() -> JsonObject:
    return BridgeCapabilities(
        backends=sorted(_BACKENDS),
        public_surfaces=[*MCP_SURFACE_PATHS.values(), "/admin"],
        features=[
            "mcp",
            "streamable-http",
            "gateway",
            "central-oauth",
            "backend-map",
            "backend-signatures",
            "generic-forwarding",
            "account-management",
            "multi-account-github",
            "multi-account-gitlab",
            "files",
            "web",
            "curl",
            "browser",
            "playwright",
            "analysis",
            "terminal",
            "jobs",
            "observability",
            "multi-account-signoz",
            "multi-account-coolify",
            "admin",
        ],
    ).to_json()


_allowed_hosts = list(_settings.http.allowed_hosts)
_allowed_origins = list(_settings.http.allowed_origins)


def _http_app(surface: FastMCP) -> Starlette:
    return surface.http_app(
        path="/mcp",
        allowed_hosts=_allowed_hosts,
        allowed_origins=_allowed_origins,
    )


def _resource_discovery_routes() -> list[BaseRoute]:
    routes: list[BaseRoute] = []
    seen_paths: set[str] = set()
    for auth in _auth_by_surface.values():
        for route in auth.get_well_known_routes(mcp_path="/mcp"):
            path = getattr(route, "path", "")
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            routes.append(route)
    return routes


_root_http_app = _http_app(mcp)
_github_http_app = _http_app(github_surface)
_gitlab_http_app = _http_app(gitlab_surface)
_files_http_app = _http_app(files_surface)
_web_http_app = _http_app(web_surface)
_analysis_http_app = _http_app(analysis_surface)
_terminal_http_app = _http_app(terminal_surface)
_observability_http_app = _http_app(observability_surface)

_MCP_HTTP_APPS = (
    _root_http_app,
    _github_http_app,
    _gitlab_http_app,
    _files_http_app,
    _web_http_app,
    _analysis_http_app,
    _terminal_http_app,
    _observability_http_app,
)
_MCP_LIFESPANS = tuple(mcp_app.router.lifespan_context for mcp_app in _MCP_HTTP_APPS)


@asynccontextmanager
async def _gateway_lifespan(app: Starlette) -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        for lifespan in _MCP_LIFESPANS:
            await stack.enter_async_context(lifespan(app))
        try:
            yield
        finally:
            await _backend_router.close()


app = Starlette(lifespan=_gateway_lifespan)

for _route in _resource_discovery_routes():
    app.router.routes.append(_route)

if _auth_settings.enabled:
    _auth_proxy = _build_auth_reverse_proxy()
    for _path in _AUTH_PROXY_PATHS:
        app.add_route(_path, _auth_proxy.handle, methods=_PROXY_METHODS)


def _websocket_backend_url(base_url: str, path: str) -> str:
    parsed = urlsplit(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit((scheme, parsed.netloc, path, "", ""))


async def _admin_browser_websocket(websocket: WebSocket) -> None:
    headers: dict[str, str] = {}
    cookie = websocket.headers.get("cookie")
    if cookie:
        headers["Cookie"] = cookie
    public_host = websocket.headers.get("host", "")
    headers["X-Forwarded-Host"] = public_host
    headers["X-Forwarded-Proto"] = websocket.headers.get("x-forwarded-proto", "https")
    await relay_websocket(
        websocket,
        _websocket_backend_url(_management_settings.url, "/admin/browser/ws"),
        headers=headers,
        origin=websocket.headers.get("origin"),
    )


_admin_proxy = ReverseProxy(_management_settings.url, backend_name="management")
_management_ui_proxy = ReverseProxy(_settings.management_ui_url, backend_name="management-ui")
app.router.routes.append(WebSocketRoute("/admin/browser/ws", _admin_browser_websocket))
app.add_route("/admin/api", _admin_proxy.handle, methods=_PROXY_METHODS)
app.add_route("/admin/api/{path:path}", _admin_proxy.handle, methods=_PROXY_METHODS)
app.add_route("/admin/legacy", _admin_proxy.handle, methods=_PROXY_METHODS)
app.add_route("/admin/legacy/{path:path}", _admin_proxy.handle, methods=_PROXY_METHODS)
app.add_route("/admin", _management_ui_proxy.handle, methods=_PROXY_METHODS)
app.add_route("/admin/{path:path}", _management_ui_proxy.handle, methods=_PROXY_METHODS)

app.mount("/github", _github_http_app)
app.mount("/gitlab", _gitlab_http_app)
app.mount("/files", _files_http_app)
app.mount("/web", _web_http_app)
app.mount("/analysis", _analysis_http_app)
app.mount("/terminal", _terminal_http_app)
app.mount("/observability", _observability_http_app)
app.mount("/", _root_http_app)
