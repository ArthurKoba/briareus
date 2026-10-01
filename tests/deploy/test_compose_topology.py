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
        "auth",
        "terminal-workspace",
        "terminal-home",
        "web-browser",
    }
    for config in volumes.values():
        assert config is None or "external" not in config


def test_persistent_mounts_use_absolute_container_paths() -> None:
    services = _services()

    assert services["management"]["volumes"] == [
        "management:/management",
        "terminal-workspace:/workspace",
    ]
    assert services["github"]["volumes"] == [
        "terminal-workspace:/workspace",
    ]
    assert services["gitlab"]["volumes"] == [
        "terminal-workspace:/workspace",
    ]
    assert services["files"]["volumes"] == [
        "terminal-workspace:/workspace",
    ]
    assert services["curl"]["volumes"] == [
        "terminal-workspace:/workspace",
        "web-browser:/browser",
    ]
    assert services["curl"]["shm_size"] == "1gb"
    assert services["auth"]["volumes"] == ["auth:/auth"]
    assert services["terminal"]["volumes"] == [
        "terminal-workspace:/workspace",
        "terminal-home:/home/agent",
    ]
    assert services["analysis"]["volumes"] == [
        "terminal-workspace:/workspace",
    ]
    assert "volumes" not in services["ghidra"]


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
            "MANAGEMENT_SERVICE_TOKEN",
            "MCP_PUBLIC_BASE_URL",
            "GITHUB_OAUTH_CLIENT_ID",
            "GITHUB_OAUTH_CLIENT_SECRET",
            "GITHUB_OAUTH_JWT_SIGNING_KEY",
            "GITHUB_OAUTH_ALLOWED_USERS",
        },
        "gateway": observability | {
            "MANAGEMENT_SERVICE_TOKEN",
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
        "TERMINAL_FILES_URL",
        "GHIDRA_MCP_URL",
        "GITHUB_AGENT_PROTECTED_BRANCHES",
        "GITHUB_AGENT_REQUIRED_CHECKS",
        "GITHUB_AGENT_REQUIRED_REVIEWERS",
        "GITLAB_PROTECTED_BRANCHES",
        "GITLAB_REGISTRY_CACHE_TTL_SECONDS",
        "FILE_WORKSPACE_ROOT",
        "FILE_UPLOAD_MAX_BYTES",
        "CURL_BINARY",
        "BROWSER_PROFILE_PATH",
        "BROWSER_EXECUTABLE_PATH",
        "BROWSER_HEADLESS",
        "BROWSER_TIMEOUT_MS",
        "BROWSER_VIEWPORT_WIDTH",
        "BROWSER_VIEWPORT_HEIGHT",
        "BROWSER_MAX_SNAPSHOT_TEXT_CHARS",
        "BROWSER_MAX_SNAPSHOT_ELEMENTS",
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


def test_entrypoint_has_no_legacy_file_dir_dependency() -> None:
    entrypoint = Path("docker-entrypoint.sh").read_text()
    assert "FILE_DIR" not in entrypoint
    assert "/files/objects" not in entrypoint
    assert "/files/tmp" not in entrypoint


def test_analysis_image_packages_workspace_dependency() -> None:
    dockerfile = Path("Dockerfile").read_text()
    analysis_stage = dockerfile.split("FROM runtime-base AS analysis", 1)[1].split(
        "FROM runtime-base AS ghidra", 1
    )[0]
    assert "COPY src/modules/files ./src/modules/files" in analysis_stage
    assert "FILE_WORKSPACE_ROOT=/workspace" in analysis_stage


def test_web_image_packages_persistent_browser_runtime() -> None:
    dockerfile = Path("Dockerfile").read_text()
    web_stage = dockerfile.split("FROM runtime-base AS curl", 1)[1].split(
        "FROM runtime-base AS terminal", 1
    )[0]

    assert "chromium" in web_stage
    assert "uv sync --frozen --no-dev --group web --no-install-project" in web_stage
    assert "BROWSER_PROFILE_PATH=/browser/profile" in web_stage
    assert "BROWSER_EXECUTABLE_PATH=/usr/bin/chromium" in web_stage
    assert "XDG_CONFIG_HOME=/browser/config" in web_stage
    assert "XDG_CACHE_HOME=/browser/cache" in web_stage
    assert "BREAKPAD_DUMP_LOCATION=/browser/crash" in web_stage


def test_entrypoint_owns_browser_profile_volume_before_dropping_privileges() -> None:
    entrypoint = Path("docker-entrypoint.sh").read_text()
    assert 'BROWSER_PROFILE_PATH="${BROWSER_PROFILE_PATH:-}"' in entrypoint
    assert (
        'chown 1000:1000 "$(dirname "${BROWSER_PROFILE_PATH}")" "${BROWSER_PROFILE_PATH}"'
        in entrypoint
    )
