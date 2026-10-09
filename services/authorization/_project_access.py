"""Internal A1 project access boundary, not an accepted public C1 API.

Callers must already have a verified connection credential. An AgentSession
UUID cannot authenticate a caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from common.platform_ids import (
    PlatformProjectId,
    TeamId,
    UserId,
)


class AuthenticationMethod(StrEnum):
    OAUTH = "oauth"
    LOCAL_LOGIN = "local_login"


class PlatformRole(StrEnum):
    USER = "user"
    SUPERUSER = "superuser"


class ProjectPermission(StrEnum):
    USE_RESOURCES = "use_resources"
    APPROVE_AGENT_SESSION = "approve_agent_session"


@dataclass(frozen=True, slots=True)
class CallerPrincipal:
    """Verified identity; not by itself an authorization grant."""

    user_id: UserId
    authentication_method: AuthenticationMethod
    # Current connection proof, not a permission token or reusable UI claim.
    # Local login must provide both fields; OAuth transport remains C2-gated.
    credential_version: int | None = None
    admin_jti_digest: str | None = None


@dataclass(frozen=True, slots=True)
class UserAccessState:
    """Current Identity state, not a role trusted from an old bearer."""

    enabled: bool
    role: PlatformRole


class ProjectAccessError(Exception):
    """Authorization application boundary error."""


class InvalidProjectOwnership(ProjectAccessError):
    """A Project projection violates its exclusive owner invariant."""


@dataclass(frozen=True, slots=True)
class ProjectOwnership:
    project_id: PlatformProjectId
    owner_user_id: UserId | None = None
    owner_team_id: TeamId | None = None

    def __post_init__(self) -> None:
        if (self.owner_user_id is None) == (self.owner_team_id is None):
            raise InvalidProjectOwnership(
                "project ownership requires exactly one User or Team owner"
            )


class UserAccessPort(Protocol):
    async def get_current_user(self, user_id: UserId) -> UserAccessState | None: ...


class ProjectOwnershipPort(Protocol):
    async def get_ownership(self, project_id: PlatformProjectId) -> ProjectOwnership | None: ...


class TeamMembershipPort(Protocol):
    async def is_active_member(self, team_id: TeamId, user_id: UserId) -> bool: ...


class ProjectAccessAuthorizer:
    """Application policy for MVP project operations and approvals.

    This does not authorize Team administration, Project ownership transfers,
    or AgentSession grants/TTL; each needs its own independent check.
    """

    def __init__(
        self,
        *,
        users: UserAccessPort,
        projects: ProjectOwnershipPort,
        memberships: TeamMembershipPort,
    ) -> None:
        self._users = users
        self._projects = projects
        self._memberships = memberships

    async def allows(
        self,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        permission: ProjectPermission,
    ) -> bool:
        if permission not in {
            ProjectPermission.USE_RESOURCES,
            ProjectPermission.APPROVE_AGENT_SESSION,
        }:
            return False

        # Adapters must fail closed on unavailable current-state data.
        user = await self._users.get_current_user(caller.user_id)
        if user is None or not user.enabled:
            return False

        ownership = await self._projects.get_ownership(project_id)
        if ownership is None or ownership.project_id != project_id:
            return False

        if user.role is PlatformRole.SUPERUSER:
            return True
        if ownership.owner_user_id is not None:
            return ownership.owner_user_id == caller.user_id

        # MVP grants all active Team members access to Team projects
        # and the ability to approve AgentSession elevation.
        if ownership.owner_team_id is not None:
            return await self._memberships.is_active_member(ownership.owner_team_id, caller.user_id)
        return False
