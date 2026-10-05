from __future__ import annotations

from enum import IntEnum
from urllib.parse import urlsplit, urlunsplit


class McpSurface(IntEnum):
    BRIDGE = 0
    GITHUB = 1
    GITLAB = 2
    FILES = 3
    WEB = 4
    ANALYSIS = 5
    TERMINAL = 6
    OBSERVABILITY = 7


MCP_SURFACE_IDS: dict[str, McpSurface] = {
    "root": McpSurface.BRIDGE,
    "github": McpSurface.GITHUB,
    "gitlab": McpSurface.GITLAB,
    "files": McpSurface.FILES,
    "web": McpSurface.WEB,
    "analysis": McpSurface.ANALYSIS,
    "terminal": McpSurface.TERMINAL,
    "observability": McpSurface.OBSERVABILITY,
}


def surface_id(surface: str) -> McpSurface:
    try:
        return MCP_SURFACE_IDS[surface]
    except KeyError as exc:
        raise ValueError(f"unknown MCP surface: {surface}") from exc


def surface_name(value: int | McpSurface) -> str:
    resolved = McpSurface(value)
    return resolved.name.casefold()

MCP_SURFACE_PATHS: dict[str, str] = {
    "root": "/mcp",
    "github": "/github/mcp",
    "gitlab": "/gitlab/mcp",
    "files": "/files/mcp",
    "web": "/web/mcp",
    "analysis": "/analysis/mcp",
    "terminal": "/terminal/mcp",
    "observability": "/observability/mcp",
}


def canonical_public_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("public MCP base URL must be absolute HTTP(S)")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def resource_url(public_base_url: str, surface: str) -> str:
    try:
        path = MCP_SURFACE_PATHS[surface]
    except KeyError as exc:
        raise ValueError(f"unknown MCP surface: {surface}") from exc
    return canonical_public_base_url(public_base_url) + path


def surface_base_url(public_base_url: str, surface: str) -> str:
    resource = resource_url(public_base_url, surface)
    if not resource.endswith("/mcp"):
        raise ValueError(f"surface resource must end in /mcp: {surface}")
    return resource[: -len("/mcp")]


def allowed_resource_urls(public_base_url: str) -> frozenset[str]:
    return frozenset(resource_url(public_base_url, surface) for surface in MCP_SURFACE_PATHS)
