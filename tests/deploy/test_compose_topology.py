from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE_FILE = Path("docker-compose.yaml")
EXPECTED_SERVICES = {
    "auth",
    "gateway",
    "management",
    "management-ui",
    "github",
    "gitlab",
    "files",
    "web",
    "terminal",
    "analysis",
    "ghidra",
    "observability",
    "valkey",
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


def test_valkey_is_private_ephemeral_and_resource_bounded() -> None:
    valkey = _services()["valkey"]

    assert valkey["image"] == "valkey/valkey:9.1.2-alpine"
    assert "ports" not in valkey
    assert "volumes" not in valkey
    assert "--appendonly" in valkey["command"]
    assert "--save" in valkey["command"]
    assert valkey["mem_limit"] == "192m"
    assert valkey["cpus"] == 0.5
    assert valkey["pids_limit"] == 128


def test_runtime_healthcheck_does_not_spawn_python_interpreters() -> None:
    compose = COMPOSE_FILE.read_text()
    runtime_prefix = compose.split("x-management-client:", 1)[0]
    dockerfile = Path("Dockerfile").read_text()

    assert "nc" in runtime_prefix
    assert "socket.create_connection" not in runtime_prefix
    assert 'CMD ["nc", "-z", "-w", "1", "127.0.0.1", "8000"]' in dockerfile
    assert "netcat-openbsd" in dockerfile


def test_terminal_has_hard_resource_limits() -> None:
    terminal = _services()["terminal"]

    assert terminal["mem_limit"] == "${TERMINAL_MEMORY_LIMIT:-2g}"
    assert terminal["memswap_limit"] == "${TERMINAL_MEMORY_SWAP_LIMIT:-2g}"
    assert terminal["cpus"] == "${TERMINAL_CPU_LIMIT:-1.5}"
    assert terminal["pids_limit"] == "${TERMINAL_PIDS_LIMIT:-256}"


def test_compose_declares_only_primary_runtime_dependencies() -> None:
    services = _services()

    expected = {
        "github": {"management": {"condition": "service_healthy", "required": True}},
        "gitlab": {"management": {"condition": "service_healthy", "required": True}},
        "observability": {"management": {"condition": "service_healthy", "required": True}},
        "analysis": {"ghidra": {"condition": "service_healthy", "required": True}},
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
    assert services["web"]["volumes"] == [
        "terminal-workspace:/workspace",
        "web-browser:/browser",
    ]
    assert services["web"]["shm_size"] == "1gb"
    assert services["auth"]["volumes"] == ["auth:/auth"]
    assert services["terminal"]["volumes"] == [
        "terminal-workspace:/workspace",
        "terminal-home:/home/agent",
    ]
    assert services["analysis"]["volumes"] == [
        "terminal-workspace:/workspace",
    ]
    assert "volumes" not in services["ghidra"]


def test_compose_declares_machine_cache_routing_and_bootstrap_environment() -> None:
    services = _services()
    machine = {"TZ", "LANG", "LC_ALL"}
    cache = {"VALKEY_URL"}
    management_client = {"MANAGEMENT_URL", "MANAGEMENT_SERVICE_TOKEN"}
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
    common = machine | cache | management_client | observability
    gateway_routing = {
        "GITHUB_URL",
        "GITLAB_URL",
        "FILES_URL",
        "WEB_URL",
        "ANALYSIS_URL",
        "GHIDRA_URL",
        "TERMINAL_URL",
        "OBSERVABILITY_URL",
    }
    expected = {
        "management-ui": set(),
        "management": machine
        | cache
        | observability
        | {
            "MANAGEMENT_ENCRYPTION_KEY",
            "MANAGEMENT_SERVICE_TOKEN",
            "MANAGEMENT_ADMIN_USERNAME",
            "MANAGEMENT_ADMIN_PASSWORD",
            "MANAGEMENT_SESSION_SECRET",
            "MANAGEMENT_FRONTEND_TELEMETRY_UPSTREAM_URL",
            "MANAGEMENT_FRONTEND_TELEMETRY_BEARER_TOKEN",
        },
        "auth": common
        | {
            "MCP_PUBLIC_BASE_URL",
            "GITHUB_OAUTH_CLIENT_ID",
            "GITHUB_OAUTH_CLIENT_SECRET",
            "GITHUB_OAUTH_JWT_SIGNING_KEY",
            "GITHUB_OAUTH_ALLOWED_USERS",
        },
        "gateway": common
        | gateway_routing
        | {
            "SERVICE_URL_GATEWAY_8000",
            "OAUTH_ENABLED",
            "MCP_PUBLIC_BASE_URL",
            "GITHUB_OAUTH_JWT_SIGNING_KEY",
            "GITHUB_OAUTH_ALLOWED_USERS",
            "MCP_ALLOWED_HOSTS",
            "MCP_ALLOWED_ORIGINS",
        },
        "github": common,
        "gitlab": common,
        "files": common,
        "web": cache | management_client | observability | {"TZ"},
        "terminal": common | {"TERMINAL_LANG"},
        "analysis": common | {"GHIDRA_URL"},
        "ghidra": common | {"GHIDRA_MCP_URL"},
        "observability": common,
        "valkey": machine,
    }

    for name, service in services.items():
        assert set(service.get("environment", {})) == expected[name]


def test_compose_keeps_image_only_defaults_out_of_deployment_environment() -> None:
    forbidden = {
        "ASGI_APP",
        "ASGI_FORWARDED_ALLOW_IPS",
        "MANAGEMENT_TIMEOUT_SECONDS",
        "MANAGEMENT_DATABASE_PATH",
        "MANAGEMENT_SESSION_HTTPS_ONLY",
        "AUTH_GITHUB_TOKEN_CACHE_TTL_SECONDS",
        "SIGNOZ_URL",
        "SIGNOZ_API_KEY",
        "COOLIFY_URL",
        "COOLIFY_API_TOKEN",
        "TERMINAL_FILES_URL",
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
        "BROWSER_DEVTOOLS_MCP_SCRIPT_PATH",
        "BROWSER_TIMEOUT_MS",
        "BROWSER_MAX_SNAPSHOT_TEXT_CHARS",
        "BROWSER_MAX_SNAPSHOT_ELEMENTS",
        "ANALYSIS_SCHEMA_CACHE_TTL_SECONDS",
        "TERMINAL_WORKSPACE_ROOT",
        "TERMINAL_HOME",
        "TERMINAL_SHELL",
        "TERMINAL_PATH",
        "TERMINAL_TERM",
        "TERMINAL_MAX_EXEC_OUTPUT_BYTES",
        "TERMINAL_MAX_JOB_READ_BYTES",
        "TERMINAL_MAX_JOB_LOG_BYTES",
    }

    for name, service in _services().items():
        assert forbidden.isdisjoint(service.get("environment", {})), name


def test_compose_marks_only_external_oauth_inputs_as_required() -> None:
    serialized = COMPOSE_FILE.read_text()
    required = {
        "GITHUB_OAUTH_CLIENT_ID",
        "GITHUB_OAUTH_CLIENT_SECRET",
        "GITHUB_OAUTH_ALLOWED_USERS",
    }
    generated = {
        "SERVICE_REALBASE64_32_MANAGEMENT_ENCRYPTION_KEY",
        "SERVICE_REALBASE64_64_MANAGEMENT_SERVICE_TOKEN",
        "SERVICE_PASSWORD_64_MANAGEMENT_ADMIN",
        "SERVICE_REALBASE64_64_MANAGEMENT_SESSION_SECRET",
        "SERVICE_REALBASE64_64_GITHUB_OAUTH_JWT_SIGNING_KEY",
        "SERVICE_URL_GATEWAY_8000",
        "SERVICE_FQDN_GATEWAY_8000",
    }

    for name in required:
        assert f"${{{name}:?}}" in serialized
    for name in generated:
        assert name in serialized

    assert "${MANAGEMENT_ENCRYPTION_KEY:?}" not in serialized
    assert "${MANAGEMENT_SERVICE_TOKEN:?}" not in serialized
    assert "${MANAGEMENT_ADMIN_PASSWORD:?}" not in serialized
    assert "${MANAGEMENT_SESSION_SECRET:?}" not in serialized
    assert "${GITHUB_OAUTH_JWT_SIGNING_KEY:?}" not in serialized
    assert "${MCP_PUBLIC_BASE_URL:?}" not in serialized
    assert "${MCP_ALLOWED_HOSTS:?}" not in serialized
    assert "${MCP_ALLOWED_ORIGINS:?}" not in serialized
    assert "SERVICE_URL_GATEWAY_8000: /" in serialized


def test_compose_exposes_machine_and_internal_routing_overrides() -> None:
    serialized = COMPOSE_FILE.read_text()

    assert "TZ: ${TZ:-UTC}" in serialized
    assert "LANG: ${LANG:-C.UTF-8}" in serialized
    assert "LC_ALL: ${LC_ALL:-C.UTF-8}" in serialized
    assert "VALKEY_URL: ${VALKEY_URL:-redis://valkey:6379/0}" in serialized
    assert "MANAGEMENT_URL: ${MANAGEMENT_URL:-http://management:8000}" in serialized
    assert "GITHUB_URL: ${GITHUB_URL:-http://github:8000/mcp}" in serialized
    assert "GHIDRA_MCP_URL: ${GHIDRA_MCP_URL:-http://bridge:8081/mcp}" in serialized


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
        if name in {"valkey", "management-ui"}:
            continue
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
    web_stage = dockerfile.split("FROM runtime-base AS web", 1)[1].split(
        "FROM runtime-base AS terminal", 1
    )[0]

    assert "chromium" in web_stage
    assert "uv sync --frozen --no-dev --group web --no-install-project" in web_stage
    assert "BROWSER_PROFILE_PATH=/browser/profile" in web_stage
    assert "BROWSER_EXECUTABLE_PATH=/usr/bin/chromium" in web_stage
    assert "COPY --from=chrome-devtools-mcp /usr/local/bin/node /usr/local/bin/node" in web_stage
    assert (
        "COPY --from=chrome-devtools-mcp /opt/chrome-devtools-mcp /opt/chrome-devtools-mcp"
    ) in web_stage
    assert "BROWSER_DEVTOOLS_MCP_SCRIPT_PATH=/opt/chrome-devtools-mcp" in web_stage
    assert "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1" in web_stage
    assert "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1" in web_stage
    assert "CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY=1" in web_stage
    assert "chrome-devtools-mcp@1.10.1" in dockerfile
    assert "XDG_CONFIG_HOME=/browser/config" in web_stage
    assert "XDG_CACHE_HOME=/browser/cache" in web_stage
    assert "BREAKPAD_DUMP_LOCATION=/browser/crash" in web_stage


def test_web_gpu_passthrough_is_render_node_only_and_unprivileged() -> None:
    compose = yaml.safe_load(COMPOSE_FILE.read_text())
    web = compose["services"]["web"]

    assert web["devices"] == [
        "${BROWSER_DRI_DEVICE:-/dev/dri/renderD128}:${BROWSER_DRI_DEVICE:-/dev/dri/renderD128}"
    ]
    assert "privileged" not in web
    assert "cap_add" not in web
    assert "pid" not in web
    assert "network_mode" not in web


def test_web_image_packages_gpu_userspace_without_kernel_driver() -> None:
    dockerfile = Path("Dockerfile").read_text()
    web_stage = dockerfile.split("FROM runtime-base AS web", 1)[1].split(
        "FROM runtime-base AS terminal", 1
    )[0]

    for package in (
        "libegl1",
        "libgbm1",
        "libgl1-mesa-dri",
        "libglx-mesa0",
        "libva2",
        "mesa-vulkan-drivers",
        "vainfo",
        "intel-media-va-driver",
    ):
        assert package in web_stage


def test_entrypoint_drops_privileges_with_only_render_group() -> None:
    entrypoint = Path("docker-entrypoint.sh").read_text()

    assert "stat -c '%g' /dev/dri/renderD128" in entrypoint
    assert "setpriv --reuid=1000 --regid=1000" in entrypoint
    assert '--groups "${GPU_RENDER_GID}"' in entrypoint
    assert "--no-new-privs" in entrypoint
    assert "chmod" not in entrypoint
    assert "chown /dev/dri" not in entrypoint


def test_web_timezone_is_optional_with_utc_fallback() -> None:
    serialized = COMPOSE_FILE.read_text()

    assert "TZ: ${TZ:-UTC}" in serialized
    assert "${TZ:?}" not in serialized


def test_entrypoint_does_not_rewrite_browser_desktop_identity() -> None:
    entrypoint = Path("docker-entrypoint.sh").read_text()

    assert "TZ=Europe/Moscow" not in entrypoint
    assert "LANG=ru_RU.UTF-8" not in entrypoint
    assert "DISPLAY=:99" not in entrypoint
    assert "export TZ LANG LC_ALL DISPLAY" not in entrypoint


def test_entrypoint_owns_browser_profile_volume_before_dropping_privileges() -> None:
    entrypoint = Path("docker-entrypoint.sh").read_text()
    assert 'BROWSER_PROFILE_PATH="${BROWSER_PROFILE_PATH:-}"' in entrypoint
    assert (
        'chown 1000:1000 "$(dirname "${BROWSER_PROFILE_PATH}")" "${BROWSER_PROFILE_PATH}"'
        in entrypoint
    )
