from __future__ import annotations

from fastmcp.server import create_proxy

from common.runtime_common import build_private_mcp, private_http_app
from common.settings import GhidraSettings, PrivateRuntimeSettings

_private_settings = PrivateRuntimeSettings()
_ghidra_settings = GhidraSettings()

mcp = build_private_mcp("ghidra", observability_scope="ghidra")
mcp.mount(
    server=create_proxy(
        _ghidra_settings.backend_url,
        name="ghidra-native",
        mode="auto",
    )
)

app = private_http_app(mcp, _private_settings)
