from __future__ import annotations

from cryptography.fernet import Fernet
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from common.settings import ManagementSettings
from management.presentation.web_api import build_admin_api_router


def _client() -> TestClient:
    settings = ManagementSettings(
        encryption_key=Fernet.generate_key().decode(),
        service_token="service-token",
        admin_username="admin",
        admin_password="password",
        session_secret="session-secret",
        session_https_only=False,
    )
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=False)
    app.include_router(build_admin_api_router(settings))
    return TestClient(app)


def test_admin_api_session_login_bootstrap_and_logout() -> None:
    with _client() as client:
        session = client.get("/admin/api/session")
        assert session.status_code == 200
        assert session.json() == {"authenticated": False, "username": None}

        login = client.post(
            "/admin/api/login",
            json={"username": "admin", "password": "password"},
        )
        assert login.status_code == 200
        assert login.json() == {"authenticated": True, "username": "admin"}

        bootstrap = client.get("/admin/api/bootstrap")
        assert bootstrap.status_code == 200
        body = bootstrap.json()
        assert body["product"] == "MCP Management"
        assert body["legacy_admin_path"] == "/admin/"
        assert {item["id"] for item in body["navigation"]} >= {"browser", "files", "settings"}

        logout = client.post("/admin/api/logout", json={})
        assert logout.status_code == 200
        assert logout.json() == {"authenticated": False, "username": None}

        denied = client.get("/admin/api/bootstrap")
        assert denied.status_code == 401


def test_admin_api_rejects_invalid_credentials() -> None:
    with _client() as client:
        response = client.post(
            "/admin/api/login",
            json={"username": "admin", "password": "wrong"},
        )

    assert response.status_code == 401


def test_admin_api_rejects_cross_origin_mutation() -> None:
    with _client() as client:
        response = client.post(
            "/admin/api/login",
            json={"username": "admin", "password": "password"},
            headers={"Origin": "https://other.example", "Host": "mcp.koba-nexus.ru"},
        )

    assert response.status_code == 403
