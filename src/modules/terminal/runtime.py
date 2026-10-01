from __future__ import annotations

from common.runtime_common import build_private_mcp, private_http_app
from common.settings import PrivateRuntimeSettings, TerminalSettings

from .files_client import TerminalFilesClient
from .manager import TerminalManager
from .tools import register_terminal_tools

_private_settings = PrivateRuntimeSettings()
_terminal_settings = TerminalSettings()
_files = TerminalFilesClient(_terminal_settings.files_url)

mcp = build_private_mcp("terminal", observability_scope="terminal")
_manager = TerminalManager(_terminal_settings, _files)
register_terminal_tools(mcp, _manager)

app = private_http_app(mcp, _private_settings)
