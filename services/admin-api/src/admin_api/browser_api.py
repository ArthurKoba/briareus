from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable

from fastapi import APIRouter
from starlette.websockets import WebSocket

from admin_api.origin import origin_allowed
from common.browser_remote_debug import (
    BROWSER_REMOTE_DEBUG_TTL_SECONDS,
    BrowserRemoteDebugAuthError,
    verify_browser_remote_debug_token,
)
from common.settings import AdminApiSettings
from common.websocket_proxy import relay_websocket

_SESSION_KEY = "admin_api_session"
Relay = Callable[..., Awaitable[None]]


def build_browser_operator_api_router(
    settings: AdminApiSettings,
    *,
    relay: Relay = relay_websocket,
) -> APIRouter:
    router = APIRouter()

    @router.websocket("/v1/browser/cdp/{token}/page/{target_id}")
    async def browser_remote_debug_socket(websocket: WebSocket, token: str, target_id: str) -> None:
        try:
            verify_browser_remote_debug_token(
                token,
                settings.service_token,
                settings.admin_username,
                target_id,
                max_age_seconds=BROWSER_REMOTE_DEBUG_TTL_SECONDS,
            )
        except BrowserRemoteDebugAuthError:
            await websocket.close(code=4401)
            return
        await relay(
            websocket,
            f"ws://web:8000/cdp/page/{target_id}",
            headers={"Authorization": f"Bearer {settings.service_token}"},
        )

    @router.websocket("/v1/browser/operator/ws")
    async def browser_operator_api_socket(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin", "")
        public_host = websocket.headers.get("x-forwarded-host") or websocket.headers.get("host", "")
        if not origin_allowed(origin, public_host, settings.admin_ui_origin):
            await websocket.close(code=4403)
            return
        session = websocket.scope.get("session")
        username = session.get(_SESSION_KEY) if isinstance(session, dict) else None
        if not isinstance(username, str) or not hmac.compare_digest(
            username, settings.admin_username
        ):
            await websocket.close(code=4401)
            return
        await relay(
            websocket,
            "ws://web:8000/operator/ws",
            headers={"Authorization": f"Bearer {settings.service_token}"},
        )

    return router
