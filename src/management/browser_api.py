from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import APIRouter
from starlette.websockets import WebSocket

from common.settings import ManagementSettings
from common.websocket_proxy import relay_websocket

_SESSION_KEY = "management_admin"
Relay = Callable[..., Awaitable[None]]


def build_browser_operator_api_router(
    settings: ManagementSettings,
    *,
    relay: Relay = relay_websocket,
) -> APIRouter:
    router = APIRouter()

    @router.websocket("/admin/api/browser/operator/ws")
    async def browser_operator_api_socket(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin", "")
        public_host = websocket.headers.get("x-forwarded-host") or websocket.headers.get("host", "")
        if origin and urlsplit(origin).netloc.casefold() != public_host.casefold():
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
