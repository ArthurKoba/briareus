from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

from cryptography.fernet import Fernet
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from common.settings import FileSettings, ManagementSettings
from management.application.services import (
    AccountService,
    InvocationAuditService,
    ManagementConfigService,
    OAuthSessionService,
    RuntimeSettingsService,
    SnapshotService,
)
from management.infrastructure.crypto import FernetCredentialCipher
from management.infrastructure.database import Base, ManagementConfigRecord, create_database
from management.infrastructure.files import FileAdminStore
from management.infrastructure.provider_checks import ProviderConnectionVerifier
from management.infrastructure.repositories import (
    SqlAlchemyAccountRepository,
    SqlAlchemyInvocationRepository,
    SqlAlchemyManagementConfigRepository,
    SqlAlchemyOAuthSessionRepository,
    SqlAlchemyRuntimeSettingsRepository,
    SqlAlchemySnapshotRepository,
)
from management.presentation.web_api import WebApiServices, build_admin_api_router


def _client(tmp_path: Path) -> TestClient:
    database = tmp_path / "api.sqlite3"
    engine, sessions = create_database(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with sessions.begin() as session:
        session.add(ManagementConfigRecord(id=1))
    key = Fernet.generate_key().decode()
    settings = ManagementSettings(
        database_path=database,
        encryption_key=key,
        service_token="service-token",
        admin_username="admin",
        admin_password="password",
        session_secret="session-secret",
        session_https_only=False,
    )
    cipher = FernetCredentialCipher(key)
    config = ManagementConfigService(SqlAlchemyManagementConfigRepository(sessions))
    services = WebApiServices(
        accounts=AccountService(
            SqlAlchemyAccountRepository(sessions),
            cipher,
            ProviderConnectionVerifier(),
        ),
        audit=InvocationAuditService(SqlAlchemyInvocationRepository(sessions), config),
        oauth_sessions=OAuthSessionService(SqlAlchemyOAuthSessionRepository(sessions)),
        snapshots=SnapshotService(SqlAlchemySnapshotRepository(sessions)),
        config=config,
        runtime_settings=RuntimeSettingsService(SqlAlchemyRuntimeSettingsRepository(sessions)),
        files=FileAdminStore(FileSettings(workspace_root=tmp_path / "workspace")),
        reverse=Mock(
            session_settings=AsyncMock(return_value={"idle_timeout_seconds": 900.0}),
            set_idle_timeout=AsyncMock(return_value={"idle_timeout_seconds": 900.0}),
        ),
        terminal=Mock(),
        snapshot_refresher=Mock(),
    )
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=False)
    app.include_router(build_admin_api_router(settings, services))
    return TestClient(app)


def _login(client: TestClient) -> None:
    response = client.post("/admin/api/login", json={"username": "admin", "password": "password"})
    assert response.status_code == 200


def test_accounts_crud_and_dashboard(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        create = client.post(
            "/admin/api/accounts",
            json={
                "alias": "ci-github",
                "provider": "github",
                "auth_type": "github_token",
                "credential": "secret-token",
            },
        )
        assert create.status_code == 201
        account = create.json()
        assert account["alias"] == "ci-github"
        assert "credential" not in account

        listing = client.get("/admin/api/accounts")
        assert listing.status_code == 200
        assert listing.json()["count"] == 1

        account_id = account["id"]
        update = client.put(
            f"/admin/api/accounts/github/{account_id}",
            json={
                "alias": "ci-github-disabled",
                "provider": "github",
                "auth_type": "github_token",
                "enabled": False,
            },
        )
        assert update.status_code == 200
        assert update.json()["enabled"] is False

        dashboard = client.get("/admin/api/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["accounts"]["total"] == 1

        deleted = client.delete(f"/admin/api/accounts/github/{account_id}")
        assert deleted.status_code == 200


def test_settings_round_trip(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        current = client.get("/admin/api/settings")
        assert current.status_code == 200
        payload = {
            "logging_enabled": True,
            "logging_capture_payloads": False,
            "logging_retention_days": 14,
            "logging_max_records": 2000,
            "maintenance_interval_minutes": 30,
            "terminal_max_exec_timeout_seconds": 3600,
            "terminal_max_job_runtime_seconds": 7200,
            "mcp_call_timeout_seconds": 15,
            "reverse_idle_timeout_seconds": 600,
        }
        saved = client.put("/admin/api/settings", json=payload)
        assert saved.status_code == 200
        assert saved.json()["management"]["logging_retention_days"] == 14
        assert saved.json()["mcp"]["call_timeout_seconds"] == 15


def test_mutations_require_session(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.delete("/admin/api/calls")
    assert response.status_code == 401
