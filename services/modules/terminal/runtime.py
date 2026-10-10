from __future__ import annotations

from common.runtime_common import admin_api_client, private_http_app
from common.settings import AdminApiClientSettings, PrivateRuntimeSettings, TerminalSettings
from modules.project_runtime.runtime_telemetry import build_runtime_mcp

from .manager import TerminalManager
from .tools import register_terminal_tools

_private_settings = PrivateRuntimeSettings()
_terminal_settings = TerminalSettings()
_admin_api = admin_api_client(AdminApiClientSettings())
mcp, _runtime_telemetry = build_runtime_mcp("terminal", name="terminal")
_manager = TerminalManager(_terminal_settings, _admin_api)
register_terminal_tools(mcp, _manager)

app = _runtime_telemetry.attach(private_http_app(mcp, _private_settings))
