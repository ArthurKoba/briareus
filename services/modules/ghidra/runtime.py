from __future__ import annotations

from fastmcp.server import create_proxy

from common.runtime_common import admin_api_client, private_http_app
from common.settings import (
    AdminApiClientSettings,
    GhidraSettings,
    PrivateRuntimeSettings,
)
from modules.project_runtime.runtime_telemetry import build_runtime_mcp

_private_settings = PrivateRuntimeSettings()
_admin_api = admin_api_client(AdminApiClientSettings())
_ghidra_settings = GhidraSettings()

mcp, _runtime_telemetry = build_runtime_mcp("reverse", name="ghidra")
mcp.mount(
    server=create_proxy(
        _ghidra_settings.backend_url,
        name="ghidra-native",
        mode="auto",
    )
)

app = _runtime_telemetry.attach(private_http_app(mcp, _private_settings))
