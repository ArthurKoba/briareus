from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from common.settings import (
    AnalysisSettings,
    AsgiServerSettings,
    AuthServiceSettings,
    BridgeSettings,
    BrowserSettings,
    FileSettings,
    GatewayAuthSettings,
    GitHubPolicySettings,
    GitLabSettings,
    ManagementClientSettings,
    ManagementSettings,
    ObservabilitySettings,
)


def test_asgi_server_settings_parse_forwarded_allow_ips(monkeypatch) -> None:
    monkeypatch.setenv("ASGI_FORWARDED_ALLOW_IPS", "*")

    assert AsgiServerSettings().forwarded_allow_ips == "*"


def test_provider_settings_parse_only_their_own_environment(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", " Main, release ")
    monkeypatch.setenv("GITHUB_AGENT_REQUIRED_CHECKS", "test, docker , lint")
    monkeypatch.setenv("GITLAB_PROTECTED_BRANCHES", "main,stable")
    monkeypatch.setenv("GHIDRA_URL", " http://ghidra:8080/mcp ")
    monkeypatch.setenv("ANALYSIS_SCHEMA_CACHE_TTL_SECONDS", "45")
    monkeypatch.setenv("FILE_WORKSPACE_ROOT", "/tmp/mcp-files")
    monkeypatch.setenv("FILE_UPLOAD_MAX_BYTES", str(256 * 1024 * 1024))

    github = GitHubPolicySettings()
    gitlab = GitLabSettings()
    analysis = AnalysisSettings()
    files = FileSettings()

    assert github.protected_branches == {"main", "release"}
    assert github.required_checks == ("test", "docker", "lint")
    assert gitlab.protected_branches == {"main", "stable"}
    assert analysis.backend_url == "http://ghidra:8080/mcp"
    assert analysis.schema_cache_ttl_seconds == 45
    assert files.workspace_root == Path("/tmp/mcp-files")
    assert files.upload_max_bytes == 256 * 1024 * 1024


def test_unrelated_invalid_environment_does_not_break_file_settings(monkeypatch) -> None:
    monkeypatch.setenv("GITLAB_REGISTRY_CACHE_TTL_SECONDS", "not-a-number")
    monkeypatch.setenv("FILE_WORKSPACE_ROOT", "/tmp/mcp-files")

    assert FileSettings().workspace_root == Path("/tmp/mcp-files")
    with pytest.raises(ValidationError):
        GitLabSettings()


def test_bridge_settings_use_canonical_backends_by_default(monkeypatch) -> None:
    for name in (
        "GITHUB_URL",
        "GITLAB_URL",
        "FILES_URL",
        "CURL_URL",
        "ANALYSIS_URL",
        "GHIDRA_URL",
        "TERMINAL_URL",
        "OBSERVABILITY_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    assert BridgeSettings().backends == {
        "github": "http://github:8000/mcp",
        "gitlab": "http://gitlab:8000/mcp",
        "files": "http://files:8000/mcp",
        "web": "http://curl:8000/mcp",
        "analysis": "http://analysis:8000/mcp",
        "ghidra": "http://ghidra:8000/mcp",
        "terminal": "http://terminal:8000/mcp",
        "observability": "http://observability:8000/mcp",
    }


def test_bridge_build_sha_uses_coolify_source_commit(monkeypatch) -> None:
    monkeypatch.delenv("BUILD_SHA", raising=False)
    monkeypatch.setenv("SOURCE_COMMIT", "abc123")

    assert BridgeSettings().build_sha == "abc123"


def test_auth_service_bootstrap_is_typed(monkeypatch) -> None:
    monkeypatch.setenv("MCP_PUBLIC_BASE_URL", " https://mcp.example.test ")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", " client ")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", " secret ")
    monkeypatch.setenv("GITHUB_OAUTH_JWT_SIGNING_KEY", " jwt ")
    monkeypatch.setenv("GITHUB_OAUTH_ALLOWED_USERS", "ArthurKoba, ReviewerBot")
    settings = AuthServiceSettings()

    assert settings.public_base_url == "https://mcp.example.test"
    assert settings.oauth_client_id == "client"
    assert settings.oauth_client_secret == "secret"
    assert settings.oauth_jwt_signing_key == "jwt"
    assert settings.oauth_allowed_users == ("arthurkoba", "reviewerbot")


def test_gateway_auth_settings_validate_tokens_locally(monkeypatch) -> None:
    monkeypatch.setenv("OAUTH_ENABLED", "true")
    monkeypatch.setenv("MCP_PUBLIC_BASE_URL", "https://mcp.example.test")
    monkeypatch.setenv("GITHUB_OAUTH_JWT_SIGNING_KEY", " jwt ")
    monkeypatch.setenv("GITHUB_OAUTH_ALLOWED_USERS", "ArthurKoba")

    settings = GatewayAuthSettings()
    settings.validate_bootstrap()

    assert settings.enabled is True
    assert settings.public_base_url == "https://mcp.example.test"
    assert settings.oauth_jwt_signing_key == "jwt"
    assert settings.oauth_allowed_users == ("arthurkoba",)


def test_management_client_settings_allow_import_without_bootstrap(monkeypatch) -> None:
    monkeypatch.delenv("MANAGEMENT_SERVICE_TOKEN", raising=False)
    settings = ManagementClientSettings()
    assert settings.url == "http://management:8000"
    assert settings.service_token == ""


def test_management_settings_validate_bootstrap(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "control.sqlite3"
    monkeypatch.setenv("MANAGEMENT_DATABASE_PATH", str(db))
    monkeypatch.setenv("MANAGEMENT_ENCRYPTION_KEY", "key")
    monkeypatch.setenv("MANAGEMENT_SERVICE_TOKEN", "service")
    monkeypatch.setenv("MANAGEMENT_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MANAGEMENT_SESSION_SECRET", "session")

    settings = ManagementSettings()
    settings.validate_bootstrap()

    assert settings.database_path == db
    assert settings.database_url == f"sqlite:///{db}"


def test_management_settings_reject_missing_bootstrap(monkeypatch) -> None:
    for name in (
        "MANAGEMENT_ENCRYPTION_KEY",
        "MANAGEMENT_SERVICE_TOKEN",
        "MANAGEMENT_ADMIN_USERNAME",
        "MANAGEMENT_ADMIN_PASSWORD",
        "MANAGEMENT_SESSION_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match="missing management bootstrap settings"):
        ManagementSettings().validate_bootstrap()


def test_file_settings_are_frozen_and_validate_limits() -> None:
    settings = FileSettings(workspace_root=Path("/tmp/files"))

    with pytest.raises(ValidationError):
        settings.upload_max_bytes = 1

    with pytest.raises(ValidationError):
        FileSettings(workspace_root=Path("relative/path"))


def test_public_runtime_defaults_are_deployment_agnostic(monkeypatch) -> None:
    for name in ("MCP_PUBLIC_BASE_URL", "MCP_ALLOWED_HOSTS", "MCP_ALLOWED_ORIGINS"):
        monkeypatch.delenv(name, raising=False)

    auth = GatewayAuthSettings()
    bridge = BridgeSettings()

    assert auth.public_base_url == ""
    assert bridge.allowed_hosts == ("localhost:*", "127.0.0.1:*", "[::1]:*")
    assert bridge.allowed_origins == (
        "http://localhost:*",
        "http://127.0.0.1:*",
        "http://[::1]:*",
    )


def test_auth_service_requires_public_base_url(monkeypatch) -> None:
    monkeypatch.delenv("MCP_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "client")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GITHUB_OAUTH_JWT_SIGNING_KEY", "jwt")
    monkeypatch.setenv("GITHUB_OAUTH_ALLOWED_USERS", "user")

    with pytest.raises(ValueError, match="MCP_PUBLIC_BASE_URL"):
        AuthServiceSettings().validate_bootstrap()


def test_observability_settings_resolve_standard_otlp_signal_endpoints() -> None:
    settings = ObservabilitySettings(
        service_name="mcp-bridge",
        endpoint="https://otel.example.test/",
        headers="Authorization=Bearer%20token",
        resource_attributes="deployment.environment.name=production",
        timeout_ms=2500,
    )

    assert settings.enabled is True
    assert settings.signal_endpoint("logs") == "https://otel.example.test/v1/logs"
    assert settings.signal_endpoint("traces") == "https://otel.example.test/v1/traces"
    assert settings.signal_endpoint("metrics") == "https://otel.example.test/v1/metrics"
    assert settings.timeout_seconds == 2.5


def test_observability_settings_are_disabled_without_otlp_endpoint() -> None:
    settings = ObservabilitySettings()

    assert settings.enabled is False
    assert settings.signal_endpoint("logs") == ""
    assert settings.signal_endpoint("traces") == ""
    assert settings.signal_endpoint("metrics") == ""


def test_browser_devtools_upstream_uses_absolute_script_path(monkeypatch) -> None:
    monkeypatch.delenv("BROWSER_DEVTOOLS_MCP_SCRIPT_PATH", raising=False)
    settings = BrowserSettings()

    assert settings.devtools_mcp_script_path.is_absolute()
    with pytest.raises(ValidationError, match="browser paths must be absolute"):
        BrowserSettings(devtools_mcp_script_path=Path("relative/devtools.js"))
