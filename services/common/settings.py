from __future__ import annotations

from os import getenv
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_DEFAULT_PRIVATE_HOSTS = (
    "localhost:*",
    "127.0.0.1:*",
    "[::1]:*",
    "github:*",
    "gitlab:*",
    "files:*",
    "web:*",
    "analysis:*",
    "ghidra:*",
    "terminal:*",
    "observability:*",
    "auth:*",
    "access:*",
)
_DEFAULT_PRIVATE_ORIGINS = (
    "http://localhost:*",
    "http://127.0.0.1:*",
    "http://[::1]:*",
)
_DEFAULT_PUBLIC_HOSTS = ("localhost:*", "127.0.0.1:*", "[::1]:*")
_DEFAULT_PUBLIC_ORIGINS = (
    "http://localhost:*",
    "http://127.0.0.1:*",
    "http://[::1]:*",
)


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _tuple_value(value: object) -> object:
    return _csv(value) if isinstance(value, str) else value


def _frozenset_value(value: object) -> object:
    if isinstance(value, str):
        return frozenset(item.casefold() for item in _csv(value))
    if isinstance(value, (set, frozenset, tuple, list)):
        return frozenset(str(item).casefold() for item in value)
    return value


class FrozenSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HttpSurfaceSettings(FrozenSettings):
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]


class ProcessSettings(BaseSettings):
    """Immutable environment-backed configuration created only by composition roots."""

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=True,
        env_file=None,
        validate_default=True,
        populate_by_name=True,
        frozen=True,
    )


class AsgiServerSettings(ProcessSettings):
    app: str = Field("bridge.server:app", validation_alias="ASGI_APP")
    host: str = Field("0.0.0.0", validation_alias="ASGI_HOST")
    port: int = Field(8000, ge=1, le=65535, validation_alias="ASGI_PORT")
    forwarded_allow_ips: str = Field(
        "127.0.0.1",
        validation_alias="ASGI_FORWARDED_ALLOW_IPS",
    )

    @field_validator("app", "host", "forwarded_allow_ips", mode="before")
    @classmethod
    def _strip_values(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PrivateRuntimeSettings(ProcessSettings):
    allowed_hosts: Annotated[tuple[str, ...], NoDecode] = Field(
        _DEFAULT_PRIVATE_HOSTS,
        validation_alias="PRIVATE_MCP_ALLOWED_HOSTS",
    )
    allowed_origins: Annotated[tuple[str, ...], NoDecode] = Field(
        _DEFAULT_PRIVATE_ORIGINS,
        validation_alias="PRIVATE_MCP_ALLOWED_ORIGINS",
    )

    @field_validator("allowed_hosts", "allowed_origins", mode="before")
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return _tuple_value(value)

    @property
    def http(self) -> HttpSurfaceSettings:
        return HttpSurfaceSettings(
            allowed_hosts=self.allowed_hosts,
            allowed_origins=self.allowed_origins,
        )


class ValkeySettings(ProcessSettings):
    url: str = Field("redis://valkey:6379/0", validation_alias="VALKEY_URL")
    namespace: str = Field("mcp-bridge:v1", validation_alias="VALKEY_NAMESPACE")
    socket_connect_timeout_seconds: float = Field(
        0.15,
        ge=0.01,
        le=5.0,
        validation_alias="VALKEY_CONNECT_TIMEOUT_SECONDS",
    )
    socket_timeout_seconds: float = Field(
        0.25,
        ge=0.01,
        le=5.0,
        validation_alias="VALKEY_SOCKET_TIMEOUT_SECONDS",
    )
    failure_backoff_seconds: float = Field(
        5.0,
        ge=0.1,
        le=60.0,
        validation_alias="VALKEY_FAILURE_BACKOFF_SECONDS",
    )
    account_ttl_seconds: int = Field(
        120, ge=1, le=3600, validation_alias="VALKEY_ACCOUNT_TTL_SECONDS"
    )
    account_list_ttl_seconds: int = Field(
        30, ge=1, le=600, validation_alias="VALKEY_ACCOUNT_LIST_TTL_SECONDS"
    )
    policy_ttl_seconds: int = Field(30, ge=1, le=600, validation_alias="VALKEY_POLICY_TTL_SECONDS")
    admin_config_ttl_seconds: int = Field(
        30,
        ge=1,
        le=600,
        validation_alias="VALKEY_ADMIN_API_CONFIG_TTL_SECONDS",
    )

    @field_validator("url", "namespace", mode="before")
    @classmethod
    def _strip_cache_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class BridgeSettings(ProcessSettings):
    auth_url: str = Field("http://auth:8000", validation_alias="AUTH_SERVICE_URL")
    github_url: str = Field("http://github:8000/mcp", validation_alias="GITHUB_URL")
    gitlab_url: str = Field("http://gitlab:8000/mcp", validation_alias="GITLAB_URL")
    files_url: str = Field("http://files:8000/mcp", validation_alias="FILES_URL")
    web_url: str = Field("http://web:8000/mcp", validation_alias="WEB_URL")
    analysis_url: str = Field(
        "http://analysis:8000/mcp",
        validation_alias="ANALYSIS_URL",
    )
    ghidra_url: str = Field(
        "http://ghidra:8000/mcp",
        validation_alias="GHIDRA_URL",
    )
    terminal_url: str = Field(
        "http://terminal:8000/mcp",
        validation_alias="TERMINAL_URL",
    )
    observability_url: str = Field(
        "http://observability:8000/mcp",
        validation_alias="OBSERVABILITY_URL",
    )
    build_sha: str = Field(
        "unknown",
        validation_alias=AliasChoices("BUILD_SHA", "SOURCE_COMMIT"),
    )
    build_time: str = Field("unknown", validation_alias="BUILD_TIME")
    allowed_hosts: Annotated[tuple[str, ...], NoDecode] = Field(
        _DEFAULT_PUBLIC_HOSTS,
        validation_alias="MCP_ALLOWED_HOSTS",
    )
    allowed_origins: Annotated[tuple[str, ...], NoDecode] = Field(
        _DEFAULT_PUBLIC_ORIGINS,
        validation_alias="MCP_ALLOWED_ORIGINS",
    )

    @field_validator(
        "auth_url",
        "github_url",
        "gitlab_url",
        "files_url",
        "web_url",
        "analysis_url",
        "ghidra_url",
        "terminal_url",
        "observability_url",
        "build_sha",
        "build_time",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("allowed_hosts", "allowed_origins", mode="before")
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return _tuple_value(value)

    @property
    def backends(self) -> dict[str, str]:
        return {
            "github": self.github_url or "http://github:8000/mcp",
            "gitlab": self.gitlab_url or "http://gitlab:8000/mcp",
            "files": self.files_url or "http://files:8000/mcp",
            "web": self.web_url or "http://web:8000/mcp",
            "analysis": self.analysis_url or "http://analysis:8000/mcp",
            "ghidra": self.ghidra_url or "http://ghidra:8000/mcp",
            "terminal": self.terminal_url or "http://terminal:8000/mcp",
            "observability": self.observability_url or "http://observability:8000/mcp",
        }

    @property
    def http(self) -> HttpSurfaceSettings:
        return HttpSurfaceSettings(
            allowed_hosts=self.allowed_hosts,
            allowed_origins=self.allowed_origins,
        )


class ObservabilitySettings(ProcessSettings):
    service_name: str = Field("mcp-bridge", validation_alias="OTEL_SERVICE_NAME")
    service_namespace: str = Field("", validation_alias="SERVICE_NAMESPACE")
    service_version: str = Field("0.1.0", validation_alias="OTEL_SERVICE_VERSION")
    service_instance_id: str = Field("", validation_alias="OTEL_SERVICE_INSTANCE_ID")
    environment: str = Field(
        "production",
        validation_alias=AliasChoices("DEPLOYMENT_ENVIRONMENT", "OTEL_ENVIRONMENT"),
    )
    endpoint: str = Field(
        "",
        validation_alias=AliasChoices("OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT"),
    )
    bearer_token: str = Field("", validation_alias="OTLP_BEARER_TOKEN")
    logs_endpoint_override: str = Field(
        "",
        validation_alias="OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
    )
    traces_endpoint_override: str = Field(
        "",
        validation_alias="OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    )
    metrics_endpoint_override: str = Field(
        "",
        validation_alias="OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    )
    legacy_headers: str = Field(
        "",
        validation_alias="OTEL_EXPORTER_OTLP_HEADERS",
    )
    resource_attributes: str = Field("", validation_alias="OTEL_RESOURCE_ATTRIBUTES")
    log_level: str = Field("INFO", validation_alias="OTEL_LOG_LEVEL")
    timeout_ms: int = Field(
        10_000,
        ge=100,
        le=120_000,
        validation_alias="OTEL_EXPORTER_OTLP_TIMEOUT",
    )
    metric_export_interval_ms: int = Field(
        30_000,
        ge=1_000,
        le=300_000,
        validation_alias="OTEL_METRIC_EXPORT_INTERVAL",
    )

    @field_validator(
        "service_name",
        "service_namespace",
        "service_version",
        "service_instance_id",
        "environment",
        "endpoint",
        "bearer_token",
        "logs_endpoint_override",
        "traces_endpoint_override",
        "metrics_endpoint_override",
        "legacy_headers",
        "resource_attributes",
        "log_level",
        mode="before",
    )
    @classmethod
    def _strip_observability_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @property
    def enabled(self) -> bool:
        return bool(
            self.endpoint
            or self.logs_endpoint_override
            or self.traces_endpoint_override
            or self.metrics_endpoint_override
        )

    @property
    def resolved_instance_id(self) -> str:
        return self.service_instance_id or getenv("HOSTNAME") or "unknown"

    def signal_endpoint(self, signal: str) -> str:
        overrides = {
            "logs": self.logs_endpoint_override,
            "traces": self.traces_endpoint_override,
            "metrics": self.metrics_endpoint_override,
        }
        if signal not in overrides:
            raise ValueError(f"unsupported OTLP signal: {signal}")
        override = overrides[signal]
        if override:
            return override
        if not self.endpoint:
            return ""
        endpoint = self.endpoint.rstrip("/")
        for suffix in ("/v1/logs", "/v1/traces", "/v1/metrics"):
            if endpoint.endswith(suffix):
                endpoint = endpoint[: -len(suffix)]
                break
        return f"{endpoint}/v1/{signal}"

    @property
    def timeout_seconds(self) -> float:
        return self.timeout_ms / 1000


class AuthServiceSettings(ProcessSettings):
    public_base_url: str = Field("", validation_alias="MCP_PUBLIC_BASE_URL")
    postgres_host: str = Field("postgres", validation_alias="AUTH_POSTGRES_HOST")
    postgres_port: int = Field(5432, ge=1, le=65535, validation_alias="AUTH_POSTGRES_PORT")
    postgres_db: str = Field("auth", validation_alias="AUTH_POSTGRES_DB")
    postgres_user: str = Field("", validation_alias="AUTH_POSTGRES_USER")
    postgres_password: str = Field("", validation_alias="AUTH_POSTGRES_PASSWORD")
    bootstrap_username: str = Field("", validation_alias="AUTH_BOOTSTRAP_USERNAME")
    bootstrap_password: str = Field("", validation_alias="AUTH_BOOTSTRAP_PASSWORD")
    jwt_private_key_pem: str = Field("", validation_alias="AUTH_JWT_PRIVATE_KEY_PEM")
    jwt_key_id: str = Field("auth-1", validation_alias="AUTH_JWT_KEY_ID")
    access_service_token: str = Field("", validation_alias="AUTH_ACCESS_SERVICE_TOKEN")
    admin_service_token: str = Field("", validation_alias="AUTH_ADMIN_SERVICE_TOKEN")
    access_token_ttl_seconds: int = Field(
        900,
        ge=60,
        le=86_400,
        validation_alias="AUTH_ACCESS_TOKEN_TTL_SECONDS",
    )
    refresh_token_ttl_seconds: int = Field(
        30 * 24 * 60 * 60,
        ge=3600,
        le=365 * 24 * 60 * 60,
        validation_alias="AUTH_REFRESH_TOKEN_TTL_SECONDS",
    )
    allowed_redirect_uris: Annotated[tuple[str, ...], NoDecode] = Field(
        ("https://chatgpt.com/connector_platform_oauth_redirect",),
        validation_alias="AUTH_ALLOWED_REDIRECT_URIS",
    )

    @field_validator(
        "public_base_url",
        "postgres_host",
        "postgres_db",
        "postgres_user",
        "postgres_password",
        "bootstrap_username",
        "bootstrap_password",
        "jwt_private_key_pem",
        "jwt_key_id",
        "access_service_token",
        "admin_service_token",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("allowed_redirect_uris", mode="before")
    @classmethod
    def _parse_redirect_uris(cls, value: object) -> object:
        return _tuple_value(value)

    def validate_bootstrap(self) -> None:
        missing = [
            name
            for name, value in (
                ("MCP_PUBLIC_BASE_URL", self.public_base_url),
                ("AUTH_POSTGRES_USER", self.postgres_user),
                ("AUTH_POSTGRES_PASSWORD", self.postgres_password),
                ("AUTH_BOOTSTRAP_USERNAME", self.bootstrap_username),
                ("AUTH_BOOTSTRAP_PASSWORD", self.bootstrap_password),
                ("AUTH_JWT_PRIVATE_KEY_PEM", self.jwt_private_key_pem),
                ("AUTH_ACCESS_SERVICE_TOKEN", self.access_service_token),
                ("AUTH_ADMIN_SERVICE_TOKEN", self.admin_service_token),
            )
            if not value
        ]
        if missing:
            raise ValueError("missing auth bootstrap settings: " + ", ".join(missing))


class GatewayAuthSettings(ProcessSettings):
    enabled: bool = Field(False, validation_alias="OAUTH_ENABLED")
    public_base_url: str = Field("", validation_alias="MCP_PUBLIC_BASE_URL")
    jwt_public_key_pem: str = Field("", validation_alias="AUTH_JWT_PUBLIC_KEY_PEM")

    @field_validator("public_base_url", "jwt_public_key_pem", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    def validate_bootstrap(self) -> None:
        if not self.enabled:
            return
        missing = [
            name
            for name, value in (
                ("MCP_PUBLIC_BASE_URL", self.public_base_url),
                ("AUTH_JWT_PUBLIC_KEY_PEM", self.jwt_public_key_pem),
            )
            if not value
        ]
        if missing:
            raise ValueError("missing gateway auth settings: " + ", ".join(missing))


class AccessServiceSettings(ProcessSettings):
    postgres_host: str = Field("postgres", validation_alias="ACCESS_POSTGRES_HOST")
    postgres_port: int = Field(5432, ge=1, le=65535, validation_alias="ACCESS_POSTGRES_PORT")
    postgres_db: str = Field("access", validation_alias="ACCESS_POSTGRES_DB")
    postgres_user: str = Field("", validation_alias="ACCESS_POSTGRES_USER")
    postgres_password: str = Field("", validation_alias="ACCESS_POSTGRES_PASSWORD")
    gateway_service_token: str = Field("", validation_alias="ACCESS_GATEWAY_SERVICE_TOKEN")
    admin_service_token: str = Field("", validation_alias="ACCESS_ADMIN_SERVICE_TOKEN")
    auth_url: str = Field("http://auth:8000", validation_alias="AUTH_INTERNAL_URL")
    auth_service_token: str = Field("", validation_alias="AUTH_ACCESS_SERVICE_TOKEN")
    default_session_ttl_seconds: int = Field(
        3600, ge=60, le=30 * 24 * 60 * 60, validation_alias="ACCESS_DEFAULT_SESSION_TTL_SECONDS"
    )
    cache_ttl_seconds: int = Field(300, ge=5, le=3600, validation_alias="ACCESS_CACHE_TTL_SECONDS")
    invalid_attempt_soft_limit: int = Field(
        5, ge=1, le=100, validation_alias="ACCESS_INVALID_ATTEMPT_SOFT_LIMIT"
    )
    invalid_attempt_oauth_revoke_limit: int = Field(
        50, ge=5, le=10_000, validation_alias="ACCESS_INVALID_ATTEMPT_OAUTH_REVOKE_LIMIT"
    )
    invalid_attempt_window_seconds: int = Field(
        600, ge=30, le=86_400, validation_alias="ACCESS_INVALID_ATTEMPT_WINDOW_SECONDS"
    )
    invalid_attempt_backoff_seconds: int = Field(
        30, ge=1, le=3600, validation_alias="ACCESS_INVALID_ATTEMPT_BACKOFF_SECONDS"
    )

    @field_validator(
        "postgres_host",
        "postgres_db",
        "postgres_user",
        "postgres_password",
        "gateway_service_token",
        "admin_service_token",
        "auth_url",
        "auth_service_token",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    def validate_bootstrap(self) -> None:
        missing = [
            name
            for name, value in (
                ("ACCESS_POSTGRES_USER", self.postgres_user),
                ("ACCESS_POSTGRES_PASSWORD", self.postgres_password),
                ("ACCESS_GATEWAY_SERVICE_TOKEN", self.gateway_service_token),
                ("ACCESS_ADMIN_SERVICE_TOKEN", self.admin_service_token),
                ("AUTH_ACCESS_SERVICE_TOKEN", self.auth_service_token),
            )
            if not value
        ]
        if missing:
            raise ValueError("missing access bootstrap settings: " + ", ".join(missing))


class AccessClientSettings(ProcessSettings):
    enabled: bool = Field(False, validation_alias="ACCESS_ENABLED")
    url: str = Field("http://access:8000", validation_alias="ACCESS_SERVICE_URL")
    service_token: str = Field("", validation_alias="ACCESS_GATEWAY_SERVICE_TOKEN")
    timeout_seconds: float = Field(2.0, gt=0, le=30, validation_alias="ACCESS_TIMEOUT_SECONDS")

    @field_validator("url", "service_token", mode="before")
    @classmethod
    def _strip_values(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    def validate_bootstrap(self) -> None:
        if self.enabled and not self.service_token:
            raise ValueError("ACCESS_GATEWAY_SERVICE_TOKEN is required when ACCESS_ENABLED=true")


class AdminApiClientSettings(ProcessSettings):
    url: str = Field("http://admin-api:8000", validation_alias="ADMIN_API_URL")
    service_token: str = Field("", validation_alias="ADMIN_API_SERVICE_TOKEN")
    timeout_seconds: float = Field(
        10,
        gt=0,
        le=60,
        validation_alias="ADMIN_API_TIMEOUT_SECONDS",
    )

    @field_validator("url", "service_token", mode="before")
    @classmethod
    def _strip_values(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AdminApiSettings(ProcessSettings):
    postgres_host: str = Field("postgres", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, ge=1, le=65535, validation_alias="POSTGRES_PORT")
    postgres_db: str = Field("mcp-bridge", validation_alias="POSTGRES_DB")
    postgres_user: str = Field(validation_alias="POSTGRES_USER")
    postgres_password: str = Field(validation_alias="POSTGRES_PASSWORD")
    encryption_key: str = Field("", validation_alias="ADMIN_API_ENCRYPTION_KEY")
    service_token: str = Field("", validation_alias="ADMIN_API_SERVICE_TOKEN")
    access_url: str = Field("http://access:8000", validation_alias="ACCESS_SERVICE_URL")
    access_admin_service_token: str = Field(
        "", validation_alias="ACCESS_ADMIN_SERVICE_TOKEN"
    )
    auth_internal_url: str = Field("http://auth:8000", validation_alias="AUTH_INTERNAL_URL")
    auth_admin_service_token: str = Field(
        "", validation_alias="AUTH_ADMIN_SERVICE_TOKEN"
    )
    admin_username: str = Field("admin", validation_alias="ADMIN_API_USERNAME")
    admin_password: str = Field("", validation_alias="ADMIN_API_PASSWORD")
    session_secret: str = Field("", validation_alias="ADMIN_API_SESSION_SECRET")
    session_https_only: bool = Field(
        True,
        validation_alias="ADMIN_API_SESSION_HTTPS_ONLY",
    )
    admin_ui_origin: str = Field(
        "",
        validation_alias="ADMIN_UI_ORIGIN",
    )

    @field_validator(
        "postgres_host",
        "postgres_db",
        "postgres_user",
        "encryption_key",
        "service_token",
        "access_url",
        "access_admin_service_token",
        "auth_internal_url",
        "auth_admin_service_token",
        "admin_username",
        "admin_password",
        "session_secret",
        "admin_ui_origin",
        mode="before",
    )
    @classmethod
    def _strip_secrets(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    def validate_bootstrap(self) -> None:
        missing = [
            name
            for name, value in (
                ("POSTGRES_USER", self.postgres_user),
                ("POSTGRES_PASSWORD", self.postgres_password),
                ("ADMIN_API_ENCRYPTION_KEY", self.encryption_key),
                ("ADMIN_API_SERVICE_TOKEN", self.service_token),
                ("ADMIN_API_USERNAME", self.admin_username),
                ("ADMIN_API_PASSWORD", self.admin_password),
                ("ADMIN_API_SESSION_SECRET", self.session_secret),
            )
            if not value
        ]
        if missing:
            raise ValueError("missing admin_api bootstrap settings: " + ", ".join(missing))


class AnalysisSettings(ProcessSettings):
    backend_url: str = Field(
        "http://ghidra:8000/mcp",
        validation_alias="GHIDRA_URL",
    )
    schema_cache_ttl_seconds: float = Field(
        30,
        ge=0,
        le=3600,
        validation_alias="ANALYSIS_SCHEMA_CACHE_TTL_SECONDS",
    )

    @field_validator("backend_url", mode="before")
    @classmethod
    def _strip_backend_url(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class GhidraSettings(ProcessSettings):
    backend_url: str = Field(
        "http://bridge:8081/mcp",
        validation_alias="GHIDRA_MCP_URL",
    )

    @field_validator("backend_url", mode="before")
    @classmethod
    def _strip_backend_url(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class GitHubPolicySettings(ProcessSettings):
    public_reader_account: str = Field(
        "",
        validation_alias="GITHUB_PUBLIC_READER_ACCOUNT",
    )
    public_allow_anonymous_fallback: bool = Field(
        False,
        validation_alias="GITHUB_PUBLIC_ALLOW_ANONYMOUS_FALLBACK",
    )
    protected_branches: Annotated[frozenset[str], NoDecode] = Field(
        frozenset({"main", "master"}),
        validation_alias="GITHUB_AGENT_PROTECTED_BRANCHES",
    )
    required_checks: Annotated[tuple[str, ...], NoDecode] = Field(
        ("test", "docker"),
        validation_alias="GITHUB_AGENT_REQUIRED_CHECKS",
    )
    required_reviewers: Annotated[tuple[str, ...], NoDecode] = Field(
        (),
        validation_alias="GITHUB_AGENT_REQUIRED_REVIEWERS",
    )

    @field_validator("public_reader_account", mode="before")
    @classmethod
    def _strip_public_reader_account(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("protected_branches", mode="before")
    @classmethod
    def _parse_branches(cls, value: object) -> object:
        return _frozenset_value(value)

    @field_validator("required_checks", mode="before")
    @classmethod
    def _parse_checks(cls, value: object) -> object:
        return _tuple_value(value)

    @field_validator("required_reviewers", mode="before")
    @classmethod
    def _parse_reviewers(cls, value: object) -> object:
        parsed = _tuple_value(value)
        if isinstance(parsed, tuple):
            return tuple(item.casefold() for item in parsed)
        return parsed


class GitLabSettings(ProcessSettings):
    protected_branches: Annotated[frozenset[str], NoDecode] = Field(
        frozenset(),
        validation_alias="GITLAB_PROTECTED_BRANCHES",
    )
    registry_cache_ttl_seconds: float = Field(
        60,
        ge=0,
        le=3600,
        validation_alias="GITLAB_REGISTRY_CACHE_TTL_SECONDS",
    )

    @field_validator("protected_branches", mode="before")
    @classmethod
    def _parse_branches(cls, value: object) -> object:
        return _frozenset_value(value)


class FileSettings(ProcessSettings):
    workspace_root: Path = Field(
        Path("/workspace"),
        validation_alias="FILE_WORKSPACE_ROOT",
    )
    upload_max_bytes: int = Field(
        8 * 1024 * 1024 * 1024,
        ge=1024 * 1024,
        le=64 * 1024 * 1024 * 1024,
        validation_alias="FILE_UPLOAD_MAX_BYTES",
    )

    @field_validator("workspace_root")
    @classmethod
    def _absolute_root(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("FILE_WORKSPACE_ROOT must be absolute")
        return value.resolve(strict=False)


class TerminalSettings(ProcessSettings):
    workspace_root: Path = Field(
        Path("/workspace"),
        validation_alias="TERMINAL_WORKSPACE_ROOT",
    )
    home: Path = Field(
        Path("/home/agent"),
        validation_alias="TERMINAL_HOME",
    )
    shell: str = Field("/bin/bash", validation_alias="TERMINAL_SHELL")
    path: str = Field(
        "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        validation_alias="TERMINAL_PATH",
    )
    lang: str = Field("C.UTF-8", validation_alias="TERMINAL_LANG")
    term: str = Field("xterm-256color", validation_alias="TERMINAL_TERM")
    max_exec_output_bytes: int = Field(
        2 * 1024 * 1024,
        ge=1024,
        le=64 * 1024 * 1024,
        validation_alias="TERMINAL_MAX_EXEC_OUTPUT_BYTES",
    )
    max_job_read_bytes: int = Field(
        1024 * 1024,
        ge=1024,
        le=16 * 1024 * 1024,
        validation_alias="TERMINAL_MAX_JOB_READ_BYTES",
    )
    max_job_log_bytes: int = Field(
        256 * 1024 * 1024,
        ge=1024 * 1024,
        le=8 * 1024 * 1024 * 1024,
        validation_alias="TERMINAL_MAX_JOB_LOG_BYTES",
    )

    @field_validator("workspace_root", "home")
    @classmethod
    def _absolute_terminal_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("terminal paths must be absolute")
        return value.resolve(strict=False)

    @field_validator("shell", "path", "lang", "term", mode="before")
    @classmethod
    def _strip_terminal_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class BrowserSettings(ProcessSettings):
    profile_dir: Path = Field(
        Path("/browser/profile"),
        validation_alias="BROWSER_PROFILE_PATH",
    )
    executable_path: str = Field(
        "/usr/bin/chromium",
        validation_alias="BROWSER_EXECUTABLE_PATH",
    )
    timezone: str = Field("UTC", validation_alias="TZ")
    devtools_mcp_script_path: Path = Field(
        Path(
            "/opt/chrome-devtools-mcp/lib/node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js"
        ),
        validation_alias="BROWSER_DEVTOOLS_MCP_SCRIPT_PATH",
    )
    timeout_ms: int = Field(30_000, ge=1_000, le=120_000, validation_alias="BROWSER_TIMEOUT_MS")
    max_snapshot_text_chars: int = Field(
        30_000,
        ge=1_000,
        le=200_000,
        validation_alias="BROWSER_MAX_SNAPSHOT_TEXT_CHARS",
    )
    max_snapshot_elements: int = Field(
        250,
        ge=10,
        le=2_000,
        validation_alias="BROWSER_MAX_SNAPSHOT_ELEMENTS",
    )

    @field_validator("profile_dir", "devtools_mcp_script_path")
    @classmethod
    def _absolute_profile_dir(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("browser paths must be absolute")
        return value.resolve(strict=False)

    @field_validator("timezone", mode="before")
    @classmethod
    def _normalize_browser_timezone(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or "UTC"
        return value

    @field_validator("executable_path", mode="before")
    @classmethod
    def _strip_executable_path(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CurlSettings(ProcessSettings):
    binary: Path | None = Field(None, validation_alias="CURL_BINARY")

    @field_validator("binary", mode="before")
    @classmethod
    def _binary_file(cls, value: object) -> object:
        if value in {None, ""}:
            return None
        path = Path(str(value)).expanduser()
        if not path.is_file():
            raise ValueError("configured curl binary does not point to a file")
        return path
