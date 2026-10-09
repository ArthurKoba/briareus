"""Private per-call Project and AgentSession authorization for future runtimes.

This port consumes verified in-process CallerPrincipal only. No anonymous
service header or session UUID alone can create the caller. C2 network access
remains unapproved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_errors import AccessDenied
from common.platform_ids import AgentSessionUuid, PlatformProjectId, UserId

from ._platform_application import PlatformApplication
from ._platform_permissions import project_permit
from ._project_access import CallerPrincipal
from ._project_sessions import ProjectSessionService


@dataclass(frozen=True, slots=True)
class ProjectActionDecision:
    actor_user_id: UserId
    project_id: PlatformProjectId
    session_uuid: AgentSessionUuid
    operation: str
    project_access_revision: str
    agent_session_version: int
    session_hard_expires_at: datetime
    owner_scope: str
    owner_id: UUID


class ProjectActionAuthorizer:
    def __init__(self, app: PlatformApplication, sessions: ProjectSessionService) -> None:
        self.app = app
        self.sessions = sessions

    async def authorize(
        self, tx: AsyncSession, principal: CallerPrincipal,
        project_id: PlatformProjectId, session_uuid: AgentSessionUuid,
        operation: str,
    ) -> ProjectActionDecision:
        if not operation or len(operation) > 128:
            raise AccessDenied("requested operation is not supported")
        permit = await project_permit(tx, self.app, principal, project_id)
        session = await self.sessions.validate_operation(
            tx, principal, project_id, session_uuid, operation
        )
        return ProjectActionDecision(
            actor_user_id=principal.user_id,
            project_id=project_id,
            session_uuid=session.session_uuid,
            operation=operation,
            project_access_revision=permit.decision_version,
            agent_session_version=session.version,
            session_hard_expires_at=session.hard_expires_at,
            owner_scope=permit.owner_scope,
            owner_id=permit.owner_id,
        )
