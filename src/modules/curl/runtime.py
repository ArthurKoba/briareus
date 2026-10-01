from __future__ import annotations

from common.runtime_annotations import READ_EXTERNAL, READ_ONLY_LOCAL, WRITE_EXTERNAL
from common.runtime_common import build_private_mcp, management_client, private_http_app
from common.settings import (
    BrowserSettings,
    CurlSettings,
    FileSettings,
    ManagementClientSettings,
    PrivateRuntimeSettings,
)
from modules.files.workspace_store import WorkspaceFileStore

from .browser import BrowserManager
from .browser_tools import register_browser_tools
from .executor import resolve_curl_binary
from .tools import register_curl_tools

_private_settings = PrivateRuntimeSettings()
_management = management_client(ManagementClientSettings())
_file_settings = FileSettings()
_curl_settings = CurlSettings()
_browser_settings = BrowserSettings()

mcp = build_private_mcp("curl", _management, observability_scope="web")
_workspace = WorkspaceFileStore(_file_settings.workspace_root)
_curl_binary = resolve_curl_binary(_curl_settings)
_browser = BrowserManager(
    workspace=_workspace,
    profile_dir=_browser_settings.profile_dir,
    executable_path=_browser_settings.executable_path,
    headless=_browser_settings.headless,
    timeout_ms=_browser_settings.timeout_ms,
    viewport_width=_browser_settings.viewport_width,
    viewport_height=_browser_settings.viewport_height,
    max_snapshot_text_chars=_browser_settings.max_snapshot_text_chars,
    max_snapshot_elements=_browser_settings.max_snapshot_elements,
)

register_curl_tools(
    mcp,
    READ_ONLY_LOCAL,
    WRITE_EXTERNAL,
    workspace=_workspace,
    max_file_bytes=_file_settings.upload_max_bytes,
    curl_binary=_curl_binary,
)

register_browser_tools(
    mcp,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    browser=_browser,
)

app = private_http_app(mcp, _private_settings)
