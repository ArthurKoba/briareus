"""Existing MCP backend topology, kept separate from Gateway ASGI assembly.

These are historical public labels. Project domain routing after C1-B/C2 is a
separate future composition, not an alias or backdoor to these endpoints.
"""

from __future__ import annotations

from collections.abc import Mapping

from common.mcp_surfaces import MCP_SURFACE_PATHS

from .backend_router import BackendDescriptor

_BACKEND_PURPOSES: tuple[tuple[str, str], ...] = (
    ("github", "GitHub repositories, pull requests, issues, Actions and reviews"),
    ("gitlab", "GitLab projects, repositories, merge requests, issues and CI"),
    ("files", "Persistent files, uploads, collections and object lifecycle"),
    ("web", "Web access through structured curl and persistent browser automation"),
    ("analysis", "General-purpose structured analysis surface"),
    ("ghidra", "Private native analysis backend"),
    ("terminal", "Persistent Linux workspaces, commands and long-running jobs"),
    (
        "observability",
        "Unified read-only infrastructure state, logs, traces, metrics and deployments",
    ),
)


def existing_backend_descriptors(backends: Mapping[str, str]) -> tuple[BackendDescriptor, ...]:
    """Stable startup order/name/paths for existing FastMCP discovery."""
    missing = [name for name, _ in _BACKEND_PURPOSES if name not in backends]
    if missing:
        raise ValueError(f"missing backend URLs: {', '.join(missing)}")
    return tuple(
        BackendDescriptor(
            name=name,
            url=backends[name],
            public_path=MCP_SURFACE_PATHS.get(name, ""),
            purpose=purpose,
        )
        for name, purpose in _BACKEND_PURPOSES
    )
