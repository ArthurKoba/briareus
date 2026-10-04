from __future__ import annotations

from pydantic import Field

from .models import StrictModel


class TerminalRuntimePolicy(StrictModel):
    max_exec_timeout_seconds: int = Field(21_600, ge=1, le=86_400)
    max_job_runtime_seconds: int = Field(43_200, ge=1, le=604_800)


class McpRuntimePolicy(StrictModel):
    call_timeout_seconds: int = Field(5, ge=1, le=300)


class GitHubRuntimePolicy(StrictModel):
    local_first_guidance: bool = True
    local_git_transport_enabled: bool = True
    remote_source_mutations_enabled: bool = False


class GitLabRuntimePolicy(StrictModel):
    local_first_guidance: bool = True
    local_git_transport_enabled: bool = True
    remote_source_mutations_enabled: bool = False
