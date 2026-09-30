from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE_FILE = Path("docker-compose.yaml")
EXPECTED_SERVICES = {
    "auth",
    "gateway",
    "management",
    "github",
    "gitlab",
    "files",
    "curl",
    "analysis",
    "ghidra",
}


def _document() -> dict[str, object]:
    return yaml.safe_load(COMPOSE_FILE.read_text())


def _services() -> dict[str, dict[str, object]]:
    return _document()["services"]


def test_compose_keeps_runtime_services_restartable() -> None:
    services = _services()

    assert set(services) == EXPECTED_SERVICES
    for service in services.values():
        assert service.get("restart") == "unless-stopped"


def test_compose_declares_only_primary_runtime_dependencies() -> None:
    services = _services()

    expected = {
        "github": {
            "management": {"condition": "service_healthy", "required": True}
        },
        "gitlab": {
            "management": {"condition": "service_healthy", "required": True}
        },
        "analysis": {
            "ghidra": {"condition": "service_healthy", "required": True}
        },
    }

    for name, service in services.items():
        if name in expected:
            assert service.get("depends_on") == expected[name]
        else:
            assert "depends_on" not in service


def test_gateway_is_not_health_gated_on_provider_availability() -> None:
    assert "depends_on" not in _services()["gateway"]


def test_compose_does_not_publish_host_ports() -> None:
    services = _services()

    for name, service in services.items():
        assert "ports" not in service, name


def test_compose_owns_clean_named_volumes() -> None:
    volumes = _document()["volumes"]

    assert set(volumes) == {"management", "files", "auth"}
    for config in volumes.values():
        assert config is None or "external" not in config


def test_persistent_mounts_use_absolute_container_paths() -> None:
    services = _services()

    assert services["management"]["volumes"] == [
        "management:/management",
        "files:/files",
    ]
    assert services["files"]["volumes"] == ["files:/files"]
    assert services["curl"]["volumes"] == ["files:/files"]
    assert services["auth"]["volumes"] == ["auth:/auth"]


def test_compose_exposes_only_external_bootstrap_environment() -> None:
    services = _services()
    expected = {
        "management": {
            "MANAGEMENT_ENCRYPTION_KEY",
            "MANAGEMENT_SERVICE_TOKEN",
            "MANAGEMENT_ADMIN_USERNAME",
            "MANAGEMENT_ADMIN_PASSWORD",
            "MANAGEMENT_SESSION_SECRET",
        },
        "auth": {
            "MCP_PUBLIC_BASE_URL",
            "GITHUB_OAUTH_CLIENT_ID",
            "GITHUB_OAUTH_CLIENT_SECRET",
            "GITHUB_OAUTH_JWT_SIGNING_KEY",
            "GITHUB_OAUTH_ALLOWED_USERS",
        },
        "gateway": {
            "OAUTH_ENABLED",
            "MCP_PUBLIC_BASE_URL",
            "GITHUB_OAUTH_JWT_SIGNING_KEY",
            "GITHUB_OAUTH_ALLOWED_USERS",
            "MCP_ALLOWED_HOSTS",
            "MCP_ALLOWED_ORIGINS",
        },
        "github": {"MANAGEMENT_SERVICE_TOKEN"},
        "gitlab": {"MANAGEMENT_SERVICE_TOKEN"},
        "files": {"MANAGEMENT_SERVICE_TOKEN"},
        "curl": {"MANAGEMENT_SERVICE_TOKEN"},
        "analysis": {"MANAGEMENT_SERVICE_TOKEN"},
        "ghidra": {"MANAGEMENT_SERVICE_TOKEN"},
    }

    for name, service in services.items():
        assert set(service.get("environment", {})) == expected[name]


def test_compose_does_not_redeclare_image_or_code_defaults() -> None:
    forbidden = {
        "ASGI_APP",
        "ASGI_FORWARDED_ALLOW_IPS",
        "MANAGEMENT_URL",
        "MANAGEMENT_TIMEOUT_SECONDS",
        "MANAGEMENT_DATABASE_PATH",
        "MANAGEMENT_SESSION_HTTPS_ONLY",
        "AUTH_GITHUB_TOKEN_CACHE_TTL_SECONDS",
        "GITHUB_URL",
        "GITLAB_URL",
        "FILES_URL",
        "CURL_URL",
        "ANALYSIS_URL",
        "GHIDRA_URL",
        "GHIDRA_MCP_URL",
        "GITHUB_AGENT_PROTECTED_BRANCHES",
        "GITHUB_AGENT_REQUIRED_CHECKS",
        "GITHUB_AGENT_REQUIRED_REVIEWERS",
        "GITLAB_PROTECTED_BRANCHES",
        "GITLAB_REGISTRY_CACHE_TTL_SECONDS",
        "FILE_UPLOAD_MAX_BYTES",
        "FILE_UPLOAD_CHUNK_BYTES",
        "FILE_MAX_EXTRACT_FILES",
        "FILE_MAX_EXTRACT_BYTES",
        "CURL_BINARY",
        "ANALYSIS_SCHEMA_CACHE_TTL_SECONDS",
    }

    for name, service in _services().items():
        assert forbidden.isdisjoint(service.get("environment", {})), name



def test_compose_requires_all_external_bootstrap_values() -> None:
    serialized = COMPOSE_FILE.read_text()
    required = {
        "MANAGEMENT_ENCRYPTION_KEY",
        "MANAGEMENT_SERVICE_TOKEN",
        "MANAGEMENT_ADMIN_USERNAME",
        "MANAGEMENT_ADMIN_PASSWORD",
        "MANAGEMENT_SESSION_SECRET",
        "GITHUB_OAUTH_CLIENT_ID",
        "GITHUB_OAUTH_CLIENT_SECRET",
        "GITHUB_OAUTH_JWT_SIGNING_KEY",
        "GITHUB_OAUTH_ALLOWED_USERS",
        "MCP_PUBLIC_BASE_URL",
        "MCP_ALLOWED_HOSTS",
        "MCP_ALLOWED_ORIGINS",
    }

    assert "${SERVICE_" not in serialized
    for name in required:
        assert f"${{{name}:?}}" in serialized


def test_compose_keeps_oauth_enablement_optional() -> None:
    serialized = COMPOSE_FILE.read_text()
    assert "${OAUTH_ENABLED:-true}" in serialized
    assert "${OAUTH_ENABLED:?}" not in serialized
