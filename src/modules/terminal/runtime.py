from __future__ import annotations

from common.runtime_common import build_private_mcp, private_http_app
from common.settings import PrivateRuntimeSettings, TerminalSettings

from .manager import TerminalManager
from .tools import register_terminal_tools

_private_settings = PrivateRuntimeSettings()
_terminal_settings = TerminalSettings()
mcp = build_private_mcp("terminal", observability_scope="terminal")
_manager = TerminalManager(_terminal_settings)
register_terminal_tools(mcp, _manager)

app = private_http_app(mcp, _private_settings)
