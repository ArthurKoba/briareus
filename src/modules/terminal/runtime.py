from __future__ import annotations

from common.runtime_common import build_private_mcp, management_client, private_http_app
from common.settings import ManagementClientSettings, PrivateRuntimeSettings, TerminalSettings

from .manager import TerminalManager
from .tools import register_terminal_tools

_private_settings = PrivateRuntimeSettings()
_terminal_settings = TerminalSettings()
_management = management_client(ManagementClientSettings())
mcp = build_private_mcp("terminal", _management, observability_scope="terminal")
_manager = TerminalManager(_terminal_settings, _management)
register_terminal_tools(mcp, _manager)

app = private_http_app(mcp, _private_settings)
