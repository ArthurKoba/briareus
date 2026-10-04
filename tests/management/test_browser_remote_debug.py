from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from common.browser_remote_debug import (
    BrowserRemoteDebugAuthError,
    issue_browser_remote_debug_token,
    verify_browser_remote_debug_token,
)
from common.settings import ManagementSettings
from management.browser_api import build_browser_operator_api_router


def _settings() -> ManagementSettings:
    return ManagementSettings(
        database_path="/tmp/browser-remote-debug-test.sqlite3",
        encryption_key="ZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmY=",
        service_token="service-token",
        admin_username="admin",
        admin_password="password",
        session_secret="session-secret",
        session_https_only=False,
    )


def test_browser_remote_debug_token_is_bound_to_subject_and_target() -> None:
    token = issue_browser_remote_debug_token("secret", "admin", "TARGET123")
    verify_browser_remote_debug_token(token, "secret", "admin", "TARGET123")

    with pytest.raises(BrowserRemoteDebugAuthError, match="subject mismatch"):
        verify_browser_remote_debug_token(token, "secret", "other", "TARGET123")
    with pytest.raises(BrowserRemoteDebugAuthError, match="target mismatch"):
        verify_browser_remote_debug_token(token, "secret", "admin", "TARGET456")
    with pytest.raises(BrowserRemoteDebugAuthError, match="invalid"):
        verify_browser_remote_debug_token(token + "broken", "secret", "admin", "TARGET123")


def test_browser_remote_debug_websocket_requires_valid_target_token() -> None:
    settings = _settings()
    relayed: list[tuple[str, dict[str, object]]] = []

    async def relay(websocket, target_url: str, **kwargs: object) -> None:
        relayed.append((target_url, kwargs))
        await websocket.accept()
        await websocket.close()

    app = FastAPI()
    app.include_router(build_browser_operator_api_router(settings, relay=relay))
    token = issue_browser_remote_debug_token(
        settings.service_token, settings.admin_username, "TARGET123"
    )

    with TestClient(app) as client:
        with (
            client.websocket_connect(f"/admin/api/browser/cdp/{token}/page/TARGET123") as websocket,
            pytest.raises(WebSocketDisconnect),
        ):
            websocket.receive_text()

        with (
            pytest.raises(WebSocketDisconnect) as invalid,
            client.websocket_connect(f"/admin/api/browser/cdp/{token}/page/TARGET456"),
        ):
            pass
        assert invalid.value.code == 4401

    assert relayed == [
        (
            "ws://web:8000/cdp/page/TARGET123",
            {"headers": {"Authorization": "Bearer service-token"}},
        )
    ]
