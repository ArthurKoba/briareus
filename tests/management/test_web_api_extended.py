from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from common.settings import FileSettings, ManagementSettings
from management.application.ports import ConnectionVerifier
from management.application.services import (
    AccountService,
    InvocationAuditService,
    ManagementConfigService,
    OAuthSessionService,
    RuntimeSettingsService,
    SnapshotService,
)
from management.domain.accounts import Account
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


class _CandidateVerifier:
    def __init__(self, *, fail: str = "") -> None:
        self.fail = fail
        self.calls: list[tuple[Account, str]] = []

    def verify(self, account: Account, credential: str) -> dict[str, object]:
        self.calls.append((account, credential))
        if self.fail:
            raise ValueError(self.fail)
        return {"ok": True, "provider": account.provider.value, "secret_echo": credential}


def _client(tmp_path: Path, *, verifier: ConnectionVerifier | None = None) -> TestClient:
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
            verifier or ProviderConnectionVerifier(),
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
        web=Mock(
            status=AsyncMock(
                return_value={"running": True, "capabilities": {"set_viewport": True}}
            ),
            set_viewport=AsyncMock(
                return_value={"page_id": "page-1", "viewport": {"width": 1280, "height": 720}}
            ),
        ),
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
        explicit_policy = client.put(
            "/admin/api/settings",
            json={
                **payload,
                "github_local_first_guidance": False,
                "github_local_git_transport_enabled": True,
                "github_remote_source_mutations_enabled": False,
            },
        )
        assert explicit_policy.status_code == 200
        assert explicit_policy.json()["github"] == {
            "local_first_guidance": False,
            "local_git_transport_enabled": True,
            "remote_source_mutations_enabled": False,
        }

        saved = client.put("/admin/api/settings", json=payload)
        assert saved.status_code == 200
        assert saved.json()["management"]["logging_retention_days"] == 14
        assert saved.json()["mcp"]["call_timeout_seconds"] == 15
        assert saved.json()["github"] == explicit_policy.json()["github"]

        explicit_defaults = client.put(
            "/admin/api/settings",
            json={
                **payload,
                "github_local_first_guidance": True,
                "github_local_git_transport_enabled": False,
                "github_remote_source_mutations_enabled": True,
            },
        )
        assert explicit_defaults.status_code == 200
        assert explicit_defaults.json()["github"] == {
            "local_first_guidance": True,
            "local_git_transport_enabled": False,
            "remote_source_mutations_enabled": True,
        }


def test_settings_omitted_github_policy_read_failure_is_controlled(
    tmp_path: Path, monkeypatch
) -> None:
    def unavailable(_self) -> object:
        raise RuntimeError("github policy unavailable")

    monkeypatch.setattr(RuntimeSettingsService, "github_policy", unavailable)
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
    with _client(tmp_path) as client:
        _login(client)
        omitted = client.put("/admin/api/settings", json=payload)
        assert omitted.status_code == 400
        assert omitted.json()["detail"] == "github policy unavailable"

        explicit = client.put(
            "/admin/api/settings",
            json={
                **payload,
                "github_local_first_guidance": False,
                "github_local_git_transport_enabled": True,
                "github_remote_source_mutations_enabled": False,
            },
        )
        assert explicit.status_code == 200
        assert explicit.json()["github"] == {
            "local_first_guidance": False,
            "local_git_transport_enabled": True,
            "remote_source_mutations_enabled": False,
        }


def test_mutations_require_session(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.delete("/admin/api/calls")
    assert response.status_code == 401


def test_settings_revision_rejects_stale_full_put(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        first = client.get("/admin/api/settings")
        second = client.get("/admin/api/settings")
        assert first.status_code == second.status_code == 200
        first_revision = first.json()["revision"]
        assert first_revision == second.json()["revision"]
        assert len(first_revision) == 64

        payload = {
            "expected_revision": first_revision,
            "logging_enabled": True,
            "logging_capture_payloads": False,
            "logging_retention_days": 15,
            "logging_max_records": 2000,
            "maintenance_interval_minutes": 30,
            "terminal_max_exec_timeout_seconds": 3600,
            "terminal_max_job_runtime_seconds": 7200,
            "mcp_call_timeout_seconds": 15,
            "reverse_idle_timeout_seconds": 600,
        }
        saved = client.put("/admin/api/settings", json=payload)
        assert saved.status_code == 200
        assert saved.json()["management"]["logging_retention_days"] == 15
        assert saved.json()["revision"] != first_revision

        stale = client.put(
            "/admin/api/settings",
            json={**payload, "logging_retention_days": 22},
        )
        assert stale.status_code == 409
        detail = stale.json()["detail"]
        assert detail["code"] == "settings_conflict"
        assert detail["current_revision"] == saved.json()["revision"]

        current = client.get("/admin/api/settings")
        assert current.status_code == 200
        assert current.json()["management"]["logging_retention_days"] == 15
        assert current.json()["revision"] == saved.json()["revision"]


def test_settings_revision_is_optional_for_legacy_clients(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        response = client.put(
            "/admin/api/settings",
            json={
                "logging_enabled": True,
                "logging_capture_payloads": False,
                "logging_retention_days": 16,
                "logging_max_records": 2000,
                "maintenance_interval_minutes": 30,
                "terminal_max_exec_timeout_seconds": 3600,
                "terminal_max_job_runtime_seconds": 7200,
                "mcp_call_timeout_seconds": 15,
                "reverse_idle_timeout_seconds": 600,
            },
        )
        assert response.status_code == 200
        assert response.json()["management"]["logging_retention_days"] == 16
        assert len(response.json()["revision"]) == 64


@pytest.mark.parametrize(
    ("provider", "auth_type", "base_url", "external_id"),
    [
        ("github", "github_token", "", ""),
        ("gitlab", "private_token", "https://gitlab.example.test", ""),
        ("signoz", "signoz_api_key", "https://signoz.example.test", ""),
        ("coolify", "coolify_api_token", "https://coolify.example.test", ""),
    ],
)
def test_account_candidate_verify_does_not_persist_or_return_provider_payload(
    tmp_path: Path,
    provider: str,
    auth_type: str,
    base_url: str,
    external_id: str,
) -> None:
    verifier = _CandidateVerifier()
    with _client(tmp_path, verifier=verifier) as client:
        _login(client)
        before = client.get("/admin/api/accounts").json()["count"]
        response = client.post(
            "/admin/api/accounts/verify-candidate",
            json={
                "alias": f"{provider}-candidate",
                "provider": provider,
                "auth_type": auth_type,
                "base_url": base_url,
                "external_id": external_id,
                "credential": "draft-secret",
                "draft_revision": "draft-1",
            },
        )
        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "provider": provider,
            "draft_revision": "draft-1",
        }
        assert client.get("/admin/api/accounts").json()["count"] == before
        assert len(verifier.calls) == 1
        assert verifier.calls[0][1] == "draft-secret"
        assert "secret" not in response.text.casefold()


def test_account_candidate_edit_reuses_saved_credential_without_persisting_draft(
    tmp_path: Path,
) -> None:
    verifier = _CandidateVerifier()
    with _client(tmp_path, verifier=verifier) as client:
        _login(client)
        created = client.post(
            "/admin/api/accounts",
            json={
                "alias": "gitlab-existing",
                "provider": "gitlab",
                "auth_type": "private_token",
                "base_url": "https://gitlab.old.test",
                "credential": "stored-secret",
            },
        )
        assert created.status_code == 201
        account_id = created.json()["id"]
        response = client.post(
            "/admin/api/accounts/verify-candidate",
            json={
                "account_id": account_id,
                "alias": "gitlab-existing",
                "provider": "gitlab",
                "auth_type": "private_token",
                "base_url": "https://gitlab.new.test",
                "credential": "",
                "draft_revision": "edit-2",
            },
        )
        assert response.status_code == 200
        candidate, credential = verifier.calls[-1]
        assert credential == "stored-secret"
        assert candidate.base_url == "https://gitlab.new.test"
        persisted = client.get("/admin/api/accounts").json()["accounts"][0]
        assert persisted["base_url"] == "https://gitlab.old.test"


def test_account_candidate_new_requires_credential(tmp_path: Path) -> None:
    verifier = _CandidateVerifier()
    with _client(tmp_path, verifier=verifier) as client:
        _login(client)
        response = client.post(
            "/admin/api/accounts/verify-candidate",
            json={
                "alias": "candidate",
                "provider": "github",
                "auth_type": "github_token",
                "credential": "",
                "draft_revision": "draft-blank",
            },
        )
        assert response.status_code == 400
        assert verifier.calls == []
        assert client.get("/admin/api/accounts").json()["count"] == 0


def test_account_candidate_verify_requires_session_and_same_origin(tmp_path: Path) -> None:
    payload = {
        "alias": "candidate",
        "provider": "github",
        "auth_type": "github_token",
        "credential": "draft-secret",
        "draft_revision": "draft-origin",
    }
    with _client(tmp_path, verifier=_CandidateVerifier()) as client:
        assert client.post("/admin/api/accounts/verify-candidate", json=payload).status_code == 401
        _login(client)
        rejected = client.post(
            "/admin/api/accounts/verify-candidate",
            json=payload,
            headers={"Origin": "https://evil.example"},
        )
        assert rejected.status_code == 403


def test_account_candidate_verify_redacts_provider_failure(tmp_path: Path) -> None:
    secret = "provider-super-secret"
    verifier = _CandidateVerifier(fail=f"upstream leaked {secret}")
    with _client(tmp_path, verifier=verifier) as client:
        _login(client)
        response = client.post(
            "/admin/api/accounts/verify-candidate",
            json={
                "alias": "candidate",
                "provider": "github",
                "auth_type": "github_token",
                "credential": secret,
                "draft_revision": "draft-error",
            },
        )
        assert response.status_code == 502
        assert response.json()["detail"] == "candidate verification failed"
        assert secret not in response.text
        assert client.get("/admin/api/accounts").json()["count"] == 0


def test_account_candidate_verify_rate_limit(tmp_path: Path) -> None:
    verifier = _CandidateVerifier()
    with _client(tmp_path, verifier=verifier) as client:
        _login(client)
        payload = {
            "alias": "candidate",
            "provider": "github",
            "auth_type": "github_token",
            "credential": "draft-secret",
            "draft_revision": "draft-rate",
        }
        for index in range(20):
            response = client.post(
                "/admin/api/accounts/verify-candidate",
                json={**payload, "draft_revision": f"draft-{index}"},
            )
            assert response.status_code == 200
        limited = client.post("/admin/api/accounts/verify-candidate", json=payload)
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"
        assert len(verifier.calls) == 20


def test_account_update_rejects_stale_revision_and_keeps_current_credential(tmp_path: Path) -> None:
    verifier = _CandidateVerifier()
    with _client(tmp_path, verifier=verifier) as client:
        _login(client)
        created = client.post(
            "/admin/api/accounts",
            json={
                "alias": "stale-check",
                "provider": "github",
                "auth_type": "github_token",
                "credential": "original-secret",
            },
        )
        assert created.status_code == 201
        account_id = created.json()["id"]
        original_updated_at = created.json()["updated_at"]

        first = client.put(
            f"/admin/api/accounts/github/{account_id}",
            json={
                "alias": "first-writer",
                "provider": "github",
                "auth_type": "github_token",
                "credential": "first-secret",
                "expected_updated_at": original_updated_at,
            },
        )
        assert first.status_code == 200
        assert first.json()["alias"] == "first-writer"
        assert first.json()["updated_at"] != original_updated_at

        stale = client.put(
            f"/admin/api/accounts/github/{account_id}",
            json={
                "alias": "stale-writer",
                "provider": "github",
                "auth_type": "github_token",
                "credential": "stale-secret",
                "expected_updated_at": original_updated_at,
            },
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "account_conflict"

        current = client.get("/admin/api/accounts").json()["accounts"][0]
        assert current["alias"] == "first-writer"
        assert current["updated_at"] == first.json()["updated_at"]

        verified = client.post(
            "/admin/api/accounts/verify-candidate",
            json={
                "account_id": account_id,
                "alias": "first-writer",
                "provider": "github",
                "auth_type": "github_token",
                "credential": "",
                "draft_revision": "after-conflict",
            },
        )
        assert verified.status_code == 200
        assert verifier.calls[-1][1] == "first-secret"
