from __future__ import annotations

from fastmcp.server import create_proxy

from common.runtime_common import admin_api_client, build_private_mcp, private_http_app
from common.settings import (
    AdminApiClientSettings,
    GhidraSettings,
    PrivateRuntimeSettings,
)

_private_settings = PrivateRuntimeSettings()
_admin_api = admin_api_client(AdminApiClientSettings())
_ghidra_settings = GhidraSettings()

mcp = build_private_mcp("ghidra", _admin_api)
mcp.mount(
    server=create_proxy(
        _ghidra_settings.backend_url,
        name="ghidra-native",
        mode="auto",
    )
)

app = private_http_app(mcp, _private_settings)
