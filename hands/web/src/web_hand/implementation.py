"""Copied functional Hand implementation, independently packaged.

This inventory is intentionally side-effect-free: importing any legacy runtime
may initialize clients, workspaces, process managers or privileged effects.
The protected HTTP/WS transport remains denied until its authorization adapter
can verify a current Rauthy identity and Cedar AgentSession grant per effect.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

SOURCE_ASGI_ENTRYPOINT = "modules.web.runtime:app"
SOURCE_TOOL_MODULES = (
    "modules.web.browser_tools",
    "modules.web.tools",
    "modules.web.devtools_proxy",
    "modules.web.external_browser_proxy",
)


def load_source_module(name: str) -> ModuleType:
    """Return an explicitly packaged source module for a trusted adapter.

    This function is deliberately not reachable from the network. Calling it
    never confers permission to execute a registered tool.
    """
    allowed = (SOURCE_ASGI_ENTRYPOINT.partition(":")[0], *SOURCE_TOOL_MODULES)
    if name not in allowed:
        raise ValueError("module is not in this Hand's source inventory")
    return import_module(name)
