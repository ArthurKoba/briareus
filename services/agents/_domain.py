"""AgentIdentity belongs to Project; does not own AgentSession or runtime."""

from dataclasses import dataclass

from common.platform_ids import AgentIdentityId, PlatformProjectId


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    id: AgentIdentityId
    project_id: PlatformProjectId
    name: str
    parent_agent_id: AgentIdentityId | None
    enabled: bool
    version: int = 1
