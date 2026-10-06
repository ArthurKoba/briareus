from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .models import StrictModel


class TerminalRuntimePolicy(StrictModel):
    max_exec_timeout_seconds: int = Field(21_600, ge=1, le=86_400)
    max_job_runtime_seconds: int = Field(43_200, ge=1, le=604_800)


class McpRuntimePolicy(StrictModel):
    call_timeout_seconds: int = Field(5, ge=1, le=300)


class BrowserRuntimePolicy(StrictModel):
    external_enabled: bool = False
    external_mcp_url: str = ""
    call_timeout_seconds: int = Field(300, ge=1, le=1800)
    auto_disconnect_enabled: bool = False
    idle_timeout_seconds: int = Field(300, ge=30, le=86_400)
    profile_dir_name: str = Field("Default", min_length=1, max_length=128)
    extension_token_configured: bool = False

    @model_validator(mode="after")
    def validate_endpoint(self) -> BrowserRuntimePolicy:
        value = self.external_mcp_url.strip()
        if value:
            parts = urlsplit(value)
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                raise ValueError("external browser MCP URL must be an absolute HTTP(S) URL")
            if parts.username is not None or parts.password is not None:
                raise ValueError("external browser MCP URL must not contain credentials")
            if parts.fragment:
                raise ValueError("external browser MCP URL must not contain a fragment")
        if self.external_enabled and not value:
            raise ValueError(
                "external browser MCP URL is required when external browser is enabled"
            )
        object.__setattr__(self, "external_mcp_url", value)
        object.__setattr__(self, "profile_dir_name", self.profile_dir_name.strip() or "Default")
        return self


class BrowserLauncherPolicy(BrowserRuntimePolicy):
    extension_token: str = ""


class GitHubRuntimePolicy(StrictModel):
    local_first_guidance: bool = True
    local_git_transport_enabled: bool = True
    remote_source_mutations_enabled: bool = False


class GitLabRuntimePolicy(StrictModel):
    local_first_guidance: bool = True
    local_git_transport_enabled: bool = True
    remote_source_mutations_enabled: bool = False
