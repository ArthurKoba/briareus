from __future__ import annotations

import platform
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime

from fastmcp import FastMCP
from fastmcp.server import create_proxy
from fastmcp.server.auth import AuthContext
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.middleware import AuthMiddleware
from starlette.applications import Starlette
from starlette.routing import BaseRoute

from common.models import JsonObject
from common.runtime_annotations import (
    DESTRUCTIVE_EXTERNAL,
    READ_EXTERNAL,
    READ_ONLY_LOCAL,
)
from common.settings import BridgeSettings, ManagementClientSettings

from . import __version__
from .admin_proxy import AdminProxy
from .backend_router import BackendDescriptor, BackendRouter
from .models import BridgeBuildInfo, BridgeCapabilities, BridgePing

_STARTED_AT = datetime.now(UTC).isoformat()
_CHATGPT_OAUTH_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
_ADMIN_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_PUBLIC_MCP_PATHS = (
    "/mcp",
    "/github/mcp",
    "/gitlab/mcp",
    "/files/mcp",
    "/web/mcp",
    "/analysis/mcp",
    "/ghidra/mcp",
)
_OAUTH_SURFACE_PREFIXES = {
    "root": "",
    "github": "/github",
    "gitlab": "/gitlab",
    "files": "/files",
    "web": "/web",
    "analysis": "/analysis",
    "ghidra": "/ghidra",
}


def _github_user_allowed(ctx: AuthContext) -> bool:
    if ctx.token is None:
        return False
    login = str(ctx.token.claims.get("login", "")).casefold()
    return bool(login) and login in _oauth_allowed_users


def _oauth_surface_url(settings: BridgeSettings, surface: str) -> str:
    try:
        prefix = _OAUTH_SURFACE_PREFIXES[surface]
    except KeyError as exc:
        raise ValueError(f"unknown OAuth surface: {surface}") from exc
    return f"{settings.oauth_base_url.rstrip('/')}{prefix}"


def _build_auth(settings: BridgeSettings) -> dict[str, GitHubProvider]:
    if not settings.oauth_enabled:
        return {}

    missing = [
        name
        for name, value in (
            ("GITHUB_OAUTH_CLIENT_ID", settings.oauth_client_id),
            ("GITHUB_OAUTH_CLIENT_SECRET", settings.oauth_client_secret),
            ("GITHUB_OAUTH_JWT_SIGNING_KEY", settings.oauth_jwt_signing_key),
        )
        if not value
    ]
    if not settings.oauth_allowed_users:
        missing.append("GITHUB_OAUTH_ALLOWED_USERS")
    if missing:
        raise RuntimeError("missing GitHub OAuth settings: " + ", ".join(missing))

    providers: dict[str, GitHubProvider] = {}
    for surface in _OAUTH_SURFACE_PREFIXES:
        surface_url = _oauth_surface_url(settings, surface)
        providers[surface] = GitHubProvider(
            client_id=settings.oauth_client_id,
            client_secret=settings.oauth_client_secret,
            base_url=surface_url,
            issuer_url=surface_url,
            required_scopes=["read:user"],
            jwt_signing_key=settings.oauth_jwt_signing_key,
            allowed_client_redirect_uris=[_CHATGPT_OAUTH_REDIRECT],
            require_authorization_consent="external",
            enable_cimd=False,
            fallback_refresh_token_expiry_seconds=30 * 24 * 60 * 60,
            fastmcp_access_token_expiry_seconds=30 * 60,
        )
    return providers


def _auth_middleware(surface: str) -> list[AuthMiddleware]:
    if surface not in _auth_by_surface:
        return []
    return [AuthMiddleware(auth=_github_user_allowed)]


def _proxy(name: str, url: str) -> FastMCP:
    return create_proxy(url, name=f"{name}-backend", mode="auto")


def _public_facade(name: str, backend_name: str, backend_url: str) -> FastMCP:
    surface = FastMCP(
        name,
        version=__version__,
        auth=_auth_by_surface.get(name),
        middleware=_auth_middleware(name),
    )
    surface.mount(server=_proxy(backend_name, backend_url))
    return surface


_settings = BridgeSettings()
_management_settings = ManagementClientSettings()
_oauth_allowed_users = frozenset(_settings.oauth_allowed_users)
_auth_by_surface = _build_auth(_settings)
_BACKENDS = _settings.backends

_backend_router = BackendRouter(
    (
        BackendDescriptor(
            "github",
            _BACKENDS["github"],
            "/github/mcp",
            "GitHub repositories, pull requests, issues, Actions and reviews",
        ),
        BackendDescriptor(
            "gitlab",
            _BACKENDS["gitlab"],
            "/gitlab/mcp",
            "GitLab projects, repositories, merge requests, issues and CI",
        ),
        BackendDescriptor(
            "files",
            _BACKENDS["files"],
            "/files/mcp",
            "Persistent files, uploads, collections and object lifecycle",
        ),
        BackendDescriptor(
            "web",
            _BACKENDS["web"],
            "/web/mcp",
            "Web access; currently curl tools, later browser/session automation",
        ),
        BackendDescriptor(
            "analysis",
            _BACKENDS["analysis"],
            "/analysis/mcp",
            "Analysis terminology facade over native Ghidra",
        ),
        BackendDescriptor(
            "ghidra",
            _BACKENDS["ghidra"],
            "/ghidra/mcp",
            "Native Ghidra MCP surface",
        ),
    )
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
    middleware=_auth_middleware("root"),
)

github_surface = _public_facade("github", "github", _BACKENDS["github"])
gitlab_surface = _public_facade("gitlab", "gitlab", _BACKENDS["gitlab"])
files_surface = _public_facade("files", "files", _BACKENDS["files"])
web_surface = _public_facade("web", "web", _BACKENDS["web"])
analysis_surface = _public_facade("analysis", "analysis", _BACKENDS["analysis"])
ghidra_surface = _public_facade("ghidra", "ghidra", _BACKENDS["ghidra"])


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
    """List public MCP backends with live availability and tool counts."""
    return await _backend_router.describe()


@mcp.tool(title="Bridge backend tools", annotations=READ_EXTERNAL)
async def bridge_tools(backend: str) -> JsonObject:
    """Fetch one backend tool catalog and signatures without publishing them at root."""
    return await _backend_router.tools(backend)


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
        public_surfaces=[*_PUBLIC_MCP_PATHS, "/admin"],
        features=[
            "mcp",
            "streamable-http",
            "gateway",
            "backend-map",
            "backend-signatures",
            "generic-forwarding",
            "account-management",
            "multi-account-github",
            "multi-account-gitlab",
            "files",
            "web",
            "curl",
            "analysis",
            "ghidra",
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


def _oauth_discovery_routes() -> list[BaseRoute]:
    """Publish RFC 8414/9728 discovery for every independently scoped MCP resource."""
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
_ghidra_http_app = _http_app(ghidra_surface)

_MCP_HTTP_APPS = (
    _root_http_app,
    _github_http_app,
    _gitlab_http_app,
    _files_http_app,
    _web_http_app,
    _analysis_http_app,
    _ghidra_http_app,
)
# Starlette does not run lifespans of mounted sub-applications. Preserve every
# FastMCP-generated lifespan before replacing the root lifespan with one owner
# that enters all session-manager contexts for the lifetime of the gateway.
_MCP_LIFESPANS = tuple(mcp_app.router.lifespan_context for mcp_app in _MCP_HTTP_APPS)


@asynccontextmanager
async def _gateway_lifespan(app: Starlette) -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        for lifespan in _MCP_LIFESPANS:
            await stack.enter_async_context(lifespan(app))
        yield


app = _root_http_app
app.router.lifespan_context = _gateway_lifespan

# Mounted FastMCP apps cannot publish their /.well-known routes at the origin root.
# ChatGPT and other MCP clients discover OAuth from the externally-visible resource
# URL. Each mounted surface owns a path-scoped authorization server and resource
# audience so RFC 8707 resource indicators cannot bleed across MCP endpoints.
for _route in reversed(_oauth_discovery_routes()):
    if getattr(_route, "path", "") not in {
        getattr(existing, "path", "") for existing in app.routes
    }:
        app.routes.insert(0, _route)
app.mount("/github", _github_http_app)
app.mount("/gitlab", _gitlab_http_app)
app.mount("/files", _files_http_app)
app.mount("/web", _web_http_app)
app.mount("/analysis", _analysis_http_app)
app.mount("/ghidra", _ghidra_http_app)

_admin_proxy = AdminProxy(_management_settings.url)
app.add_route("/admin", _admin_proxy.handle, methods=_ADMIN_METHODS)
app.add_route("/admin/{path:path}", _admin_proxy.handle, methods=_ADMIN_METHODS)
