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
    "terminal",
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

    assert set(volumes) == {
        "management",
        "files",
        "auth",
        "terminal-workspace",
        "terminal-home",
    }
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
    assert services["terminal"]["volumes"] == [
        "terminal-workspace:/workspace",
        "terminal-home:/home/agent",
        "files:/files",
    ]


def test_compose_exposes_only_external_bootstrap_environment() -> None:
    services = _services()
    observability = {
        "OTEL_SERVICE_NAME",
        "OTEL_SERVICE_VERSION",
        "OTEL_SERVICE_INSTANCE_ID",
        "OTEL_ENVIRONMENT",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_RESOURCE_ATTRIBUTES",
        "OTEL_EXPORTER_OTLP_TIMEOUT",
        "OTEL_METRIC_EXPORT_INTERVAL",
        "OTEL_LOG_LEVEL",
    }
    expected = {
        "management": observability | {
            "MANAGEMENT_ENCRYPTION_KEY",
            "MANAGEMENT_SERVICE_TOKEN",
            "MANAGEMENT_ADMIN_USERNAME",
            "MANAGEMENT_ADMIN_PASSWORD",
            "MANAGEMENT_SESSION_SECRET",
        },
        "auth": observability | {
            "MCP_PUBLIC_BASE_URL",
            "GITHUB_OAUTH_CLIENT_ID",
            "GITHUB_OAUTH_CLIENT_SECRET",
            "GITHUB_OAUTH_JWT_SIGNING_KEY",
            "GITHUB_OAUTH_ALLOWED_USERS",
        },
        "gateway": observability | {
            "OAUTH_ENABLED",
            "MCP_PUBLIC_BASE_URL",
            "GITHUB_OAUTH_JWT_SIGNING_KEY",
            "GITHUB_OAUTH_ALLOWED_USERS",
            "MCP_ALLOWED_HOSTS",
            "MCP_ALLOWED_ORIGINS",
        },
        "github": observability | {"MANAGEMENT_SERVICE_TOKEN"},
        "gitlab": observability | {"MANAGEMENT_SERVICE_TOKEN"},
        "files": observability | {"MANAGEMENT_SERVICE_TOKEN"},
        "curl": observability | {"MANAGEMENT_SERVICE_TOKEN"},
        "terminal": observability | {"MANAGEMENT_SERVICE_TOKEN"},
        "analysis": observability | {"MANAGEMENT_SERVICE_TOKEN"},
        "ghidra": observability | {"MANAGEMENT_SERVICE_TOKEN"},
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
        "TERMINAL_URL",
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
        "TERMINAL_WORKSPACE_ROOT",
        "TERMINAL_HOME",
        "TERMINAL_SHELL",
        "TERMINAL_PATH",
        "TERMINAL_LANG",
        "TERMINAL_TERM",
        "TERMINAL_MAX_EXEC_OUTPUT_BYTES",
        "TERMINAL_MAX_JOB_READ_BYTES",
        "TERMINAL_MAX_JOB_LOG_BYTES",
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


def test_compose_wires_standard_otlp_environment_to_every_service() -> None:
    services = _services()
    required = {
        "OTEL_SERVICE_NAME",
        "OTEL_SERVICE_VERSION",
        "OTEL_SERVICE_INSTANCE_ID",
        "OTEL_ENVIRONMENT",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_RESOURCE_ATTRIBUTES",
        "OTEL_EXPORTER_OTLP_TIMEOUT",
        "OTEL_METRIC_EXPORT_INTERVAL",
        "OTEL_LOG_LEVEL",
    }

    for name, service in services.items():
        assert required.issubset(service.get("environment", {})), name
