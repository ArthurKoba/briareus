from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from common.settings import ManagementSettings
from management.presentation.web_api import build_admin_api_router

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_admin_dependency_and_assets_are_removed() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text()
    lock = (ROOT / "uv.lock").read_text()
    assert "starlette-admin" not in pyproject
    assert 'name = "starlette-admin"' not in lock

    removed = [
        "src/management/presentation/admin.py",
        "src/management/presentation/admin_ui.py",
        "src/management/presentation/admin_ui_plugin",
        "src/management/presentation/templates",
        "src/management/browser_operator_auth.py",
    ]
    assert all(not (ROOT / path).exists() for path in removed)


def test_post_cutover_admin_root_is_404_and_ticket_route_is_absent(tmp_path: Path) -> None:
    settings = ManagementSettings(
        database_path=tmp_path / "management.sqlite3",
        encryption_key="not-used-by-router",
        service_token="service-token",
        admin_username="admin",
        admin_password="password",
        session_secret="session-secret",
        session_https_only=False,
    )
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=False)
    app.include_router(build_admin_api_router(settings, None))

    route_paths = {getattr(route, "path", "") for route in app.routes}
    assert "/admin/api/browser/ticket" not in route_paths

    with TestClient(app) as client:
        response = client.get("/admin")
        assert response.status_code == 404


def test_runtime_and_gateway_do_not_register_legacy_browser_ws() -> None:
    runtime = (ROOT / "src/management/runtime.py").read_text()
    gateway = (ROOT / "src/bridge/server.py").read_text()
    assert "/admin/browser/ws" not in runtime
    assert 'WebSocketRoute("/admin/browser/ws"' not in gateway
    assert 'WebSocketRoute("/api/realtime"' in gateway
    assert '"/api/browser/operator/ws"' in gateway
