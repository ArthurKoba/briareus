from __future__ import annotations

import hmac
import re

import httpx
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from common.browser_remote_debug import (
    BROWSER_REMOTE_DEBUG_TTL_SECONDS,
    BrowserRemoteDebugAuthError,
    verify_browser_remote_debug_token,
)
from common.runtime_annotations import READ_EXTERNAL, READ_ONLY_LOCAL, WRITE_EXTERNAL
from common.runtime_common import build_private_mcp, management_client, private_http_app
from common.settings import (
    BrowserSettings,
    CurlSettings,
    FileSettings,
    ManagementClientSettings,
    PrivateRuntimeSettings,
)
from common.websocket_proxy import relay_websocket
from modules.files.workspace_store import WorkspaceFileStore

from .browser import BrowserManager
from .browser_profile import DEFAULT_BROWSER_DESKTOP_PROFILE, resolve_chromium_gpu_args
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
    screen_width=_browser_profile.screen_width,
    screen_height=_browser_profile.screen_height,
    locale=_browser_profile.locale,
    accept_language=_browser_profile.accept_language,
    display=_browser_profile.display,
    color_depth=_browser_profile.color_depth,
    xvfb_enabled=_browser_profile.xvfb_enabled,
    timezone=_browser_settings.timezone,
    posix_locale=_browser_profile.posix_locale,
    chromium_args=(*_browser_profile.chromium_args, *resolve_chromium_gpu_args()),
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

_devtools = DevToolsProxyRuntime(_browser, _browser_settings)
register_browser_tools(
    mcp,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    browser=_browser,
    devtools=_devtools,
)
mcp.mount(_devtools.server, namespace="devtools")

app = private_http_app(mcp, _private_settings)


def _private_service_authorized(websocket: WebSocket) -> bool:
    authorization = websocket.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    supplied = token.strip() if scheme.casefold() == "bearer" else ""
    expected = _management.service_token
    return bool(supplied and expected and hmac.compare_digest(supplied, expected))


async def _cdp_ws(websocket: WebSocket) -> None:
    if not _private_service_authorized(websocket):
        await websocket.close(code=4401)
        return
    target_id = str(websocket.path_params.get("target_id") or "")
    if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", target_id) is None:
        await websocket.close(code=4400)
        return
    await relay_websocket(
        websocket,
        f"ws://127.0.0.1:9222/devtools/page/{target_id}",
        origin=None,
    )


async def _cdp_ui_http(request: Request) -> Response:
    token = str(request.path_params.get("token") or "")
    target_id = str(request.path_params.get("target_id") or "")
    asset_path = str(request.path_params.get("asset_path") or "")
    try:
        verify_browser_remote_debug_token(
            token,
            _management.service_token,
            None,
            target_id,
            max_age_seconds=BROWSER_REMOTE_DEBUG_TTL_SECONDS,
        )
    except BrowserRemoteDebugAuthError:
        return PlainTextResponse("Unauthorized", status_code=401)
    if not asset_path.startswith("devtools/") or ".." in asset_path.split("/"):
        return PlainTextResponse("Not Found", status_code=404)
    target = f"http://127.0.0.1:9222/{asset_path}"
    if request.url.query:
        target += "?" + request.url.query
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            upstream = await client.get(target)
    except httpx.RequestError:
        return PlainTextResponse("Chrome DevTools frontend unavailable", status_code=502)
    body = upstream.content
    content_type = upstream.headers.get("content-type", "application/octet-stream")
    if any(kind in content_type for kind in ("text/", "javascript", "json")):
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            public_prefix = f"/api/browser/devtools/{token}/page/{target_id}"
            text = text.replace("/devtools/", f"{public_prefix}/devtools/")
            body = text.encode("utf-8")
    headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.casefold()
        not in {"content-length", "content-encoding", "transfer-encoding", "connection"}
    }
    headers["cache-control"] = "no-store"
    return Response(body, status_code=upstream.status_code, headers=headers, media_type=None)


async def _operator_ws(websocket: WebSocket) -> None:
    await browser_operator_websocket(
        websocket,
        browser=_browser,
        service_token=_management.service_token,
    )


app.router.routes.extend(
    [
        Route(
            "/cdp-ui/{token}/page/{target_id}/{asset_path:path}",
            _cdp_ui_http,
            methods=["GET"],
        ),
        WebSocketRoute("/operator/ws", _operator_ws),
        WebSocketRoute("/cdp/page/{target_id}", _cdp_ws),
    ]
)
