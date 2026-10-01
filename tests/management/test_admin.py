from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from starlette.datastructures import FormData
from starlette_admin import DateTimeField

pytest.importorskip("starlette_admin")

from common.settings import FileSettings, ManagementSettings
from management.application.services import (
    AccountService,
    InvocationAuditService,
    ManagementConfigService,
    OAuthSessionService,
)
from management.domain.telemetry import Invocation
from management.infrastructure.crypto import FernetCredentialCipher
from management.infrastructure.database import (
    Base,
    ManagementConfigRecord,
    create_database,
)
from management.infrastructure.files import FileAdminStore
from management.infrastructure.provider_checks import ProviderConnectionVerifier
from management.infrastructure.repositories import (
    SqlAlchemyAccountRepository,
    SqlAlchemyInvocationRepository,
    SqlAlchemyManagementConfigRepository,
    SqlAlchemyOAuthSessionRepository,
)
from management.presentation.admin import SettingsView, _display_invocation_tool, build_admin


def test_starlette_admin_has_provider_logging_and_file_sections(tmp_path: Path) -> None:
    database = tmp_path / "admin.sqlite3"
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
    accounts = AccountService(
        SqlAlchemyAccountRepository(sessions),
        cipher,
        ProviderConnectionVerifier(),
    )
    audit = InvocationAuditService(SqlAlchemyInvocationRepository(sessions))
    config = ManagementConfigService(SqlAlchemyManagementConfigRepository(sessions))
    oauth_sessions = OAuthSessionService(SqlAlchemyOAuthSessionRepository(sessions))
    files = FileAdminStore(FileSettings(workspace_root=tmp_path / "workspace"))

    admin = build_admin(
        engine, settings, cipher, accounts, audit, oauth_sessions, config, files
    )

    assert admin.base_url == "/admin"
    assert admin.index_view.path == "/"
    labels = {view.menu_label for view in admin._views if hasattr(view, "menu_label")}
    assert "GitHub Accounts" in labels
    assert "GitLab Accounts" in labels
    assert "MCP Calls" in labels
    assert "OAuth Sessions" in labels
    assert "Reverse" in labels
    assert "Terminal" in labels
    assert "Settings" in labels
    assert "Files" in labels

    invocation_view = next(
        view for view in admin._views if getattr(view, "menu_label", "") == "MCP Calls"
    )
    assert [field.name for field in invocation_view.fields][:5] == [
        "module",
        "tool",
        "occurred_at",
        "duration_ms",
        "status",
    ]
    assert invocation_view.fields_default_sort == [("occurred_at", True)]
    assert isinstance(invocation_view.fields[2], DateTimeField)
    engine.dispose()


def test_analysis_invocation_tool_uses_public_semantic_name() -> None:
    old = SimpleNamespace(module="analysis", tool="disassemble_bytes")
    current = SimpleNamespace(module="analysis", tool="analyze_byte_region")
    other = SimpleNamespace(module="files", tool="file_list")

    assert _display_invocation_tool(None, old) == "analyze_byte_region"
    assert _display_invocation_tool(None, current) == "analyze_byte_region"
    assert _display_invocation_tool(None, other) == "file_list"


def test_invocation_audit_service_records_and_clears_admin_history(tmp_path: Path) -> None:
    database = tmp_path / "audit.sqlite3"
    engine, sessions = create_database(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with sessions.begin() as session:
        session.add(ManagementConfigRecord(id=1))

    audit = InvocationAuditService(SqlAlchemyInvocationRepository(sessions))
    audit.record(
        Invocation(
            module="analysis",
            tool="analyze_byte_region",
            status="success",
            duration_ms=5.5,
        )
    )

    recent = audit.recent()
    assert len(recent) == 1
    assert recent[0].tool == "analyze_byte_region"
    assert audit.clear() == 1
    assert audit.recent() == []
    engine.dispose()


def test_admin_settings_parse_invocation_audit_controls() -> None:
    config = SettingsView._form_config(
        FormData(
            {
                "logging_enabled": "on",
                "logging_capture_payloads": "on",
                "logging_retention_days": "14",
                "logging_max_records": "5000",
                "maintenance_interval_minutes": "15",
            }
        )
    )

    assert config.logging_enabled is True
    assert config.logging_capture_payloads is True
    assert config.logging_retention_days == 14
    assert config.logging_max_records == 5000
    assert config.maintenance_interval_minutes == 15
