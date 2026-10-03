from __future__ import annotations

from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket

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
from .browser_profile import DEFAULT_BROWSER_DESKTOP_PROFILE
from .browser_tools import register_browser_tools
from .devtools_proxy import DevToolsProxyRuntime
from .executor import resolve_curl_binary
from .operator import browser_operator_websocket
from .tools import register_curl_tools

_private_settings = PrivateRuntimeSettings()
_management = management_client(ManagementClientSettings())
_file_settings = FileSettings()
_curl_settings = CurlSettings()
_browser_settings = BrowserSettings()
_browser_profile = DEFAULT_BROWSER_DESKTOP_PROFILE

mcp = build_private_mcp("web", _management)
_workspace = WorkspaceFileStore(_file_settings.workspace_root)
_curl_binary = resolve_curl_binary(_curl_settings)
_browser = BrowserManager(
    workspace=_workspace,
    profile_dir=_browser_settings.profile_dir,
    executable_path=_browser_settings.executable_path,
    headless=_browser_profile.headless,
    timeout_ms=_browser_settings.timeout_ms,
    viewport_width=_browser_profile.viewport_width,
    viewport_height=_browser_profile.viewport_height,
    locale=_browser_profile.locale,
    accept_language=_browser_profile.accept_language,
    display=_browser_profile.display,
    color_depth=_browser_profile.color_depth,
    xvfb_enabled=_browser_profile.xvfb_enabled,
    timezone=_browser_settings.timezone,
    posix_locale=_browser_profile.posix_locale,
    chromium_args=_browser_profile.chromium_args,
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

_devtools = DevToolsProxyRuntime(_browser, _browser_settings)
mcp.mount(_devtools.server, namespace="devtools")

app = private_http_app(mcp, _private_settings)


async def _operator_ws(websocket: WebSocket) -> None:
    await browser_operator_websocket(
        websocket,
        browser=_browser,
        service_token=_management.service_token,
    )


app.router.routes.append(WebSocketRoute("/operator/ws", _operator_ws))
