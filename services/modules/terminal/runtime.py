from __future__ import annotations

from common.runtime_common import admin_api_client, build_private_mcp, private_http_app
from common.settings import AdminApiClientSettings, PrivateRuntimeSettings, TerminalSettings

from .manager import TerminalManager
from .tools import register_terminal_tools

_private_settings = PrivateRuntimeSettings()
_terminal_settings = TerminalSettings()
_admin_api = admin_api_client(AdminApiClientSettings())
mcp = build_private_mcp("terminal", _admin_api, observability_scope="terminal")
_manager = TerminalManager(_terminal_settings, _admin_api)
register_terminal_tools(mcp, _manager)

app = private_http_app(mcp, _private_settings)
