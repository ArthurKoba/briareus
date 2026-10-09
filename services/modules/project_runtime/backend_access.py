"""Private A3 Backend authorization consumer; never an MCP endpoint.

The verified caller, live Project/Team access and AgentSession grant checks
are provided by Backend's own accepted source-port implementations. There is
no local bearer verifier or fallback to an unverified UUID.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from .authorization import (
    ProjectAccessDenied,
    ProjectAccessPort,
    ProjectAction,
    ProjectInvocation,
    ProjectPermit,
    valid_project_revision,
)

AuthenticationMethod = Literal["oauth", "local_login"]
_ACTION_GRANTS: dict[ProjectAction, str] = {
    "files.read": "files.read",
    "files.write": "files.write",
    "terminal.attach": "terminal.execute",
    "web.internal": "web.access",
    "web.remote": "web.access",
    "svc.read": "integrations.use",
    "infrastructure.read": "integrations.use",
    "resources.use": "variables.use",
}
# Missing A3 grants: `files.manage`, `reverse.import`, and a verified
# per-action external provider write grant (`svc.write`). Fail closed rather
# than treating `integrations.use` as blanket authority for destructive writes.
_DECISION_TTL = timedelta(seconds=15)


@dataclass(frozen=True, slots=True)
class CurrentAuthenticatedCaller:
    user_id: UUID
    authentication_method: AuthenticationMethod
    credential_expires_at: datetime


@dataclass(frozen=True, slots=True)
class ValidatedBackendSession:
    session_uuid: UUID
    project_id: UUID
    granted_operations: tuple[str, ...]
    status: str
    is_elevated: bool
    hard_expires_at: datetime
    version: int


@dataclass(frozen=True, slots=True)
class VerifiedProjectAccess:
    """Validated A4 ProjectActions/current ProjectPermit source projection.

    A4 publishes `project_id`, `owner_scope`, `owner_id`, 64-hex
    `decision_version`, and `permissions=["use_resources", ...]` from
    current User/Project/Team membership. The trusted port also binds the
    verified caller_id separately; untrusted REST JSON is never a permit.
    """

    project_id: UUID
    caller_user_id: UUID
    owner_scope: Literal["team", "project"]
    owner_id: UUID
    decision_version: str
    permissions: tuple[str, ...]


class BackendProjectVerifier(Protocol):
    async def verify_current_project(
        self, caller: CurrentAuthenticatedCaller, project_id: UUID
    ) -> VerifiedProjectAccess: ...


class CurrentCallerVerifier(Protocol):
    async def resolve_current_authenticated(
        self, evidence: object
    ) -> CurrentAuthenticatedCaller | None: ...


class BackendServiceVerifier(Protocol):
    """Trusted service-authentication transport boundary.

    Must authenticate the *calling runtime service* against Backend policy,
    not trust a client-supplied header, string, session UUID or principal.
    Returns the authoritative expiration of verified service credentials.
    Concrete TLS/proxy token format is Backend C1-B2-owned and unapproved.
    """

    async def verify_service_connection(self, evidence: object) -> datetime | None: ...


class BackendSessionVerifier(Protocol):
    async def validate_operation(
        self,
        caller: CurrentAuthenticatedCaller,
        project_id: UUID,
        session_uuid: UUID,
        operation: str,
    ) -> ValidatedBackendSession: ...


class BackendSourceAccessAdapter(ProjectAccessPort):
    """Checks current identity plus Project SessionService source semantics.

    A3 `ProjectSessionService.validate_operation` must back the injected
    session verifier in a transactional Backend runtime. No decision cache.
    """

    def __init__(
        self,
        *,
        caller_verifier: CurrentCallerVerifier | None = None,
        session_verifier: BackendSessionVerifier | None = None,
        service_verifier: BackendServiceVerifier | None = None,
        project_verifier: BackendProjectVerifier | None = None,
    ) -> None:
        self._caller_verifier = caller_verifier
        self._session_verifier = session_verifier
        self._service_verifier = service_verifier
        self._project_verifier = project_verifier

    async def authorize(
        self, invocation: ProjectInvocation, action: ProjectAction
    ) -> ProjectPermit:
        grant = _ACTION_GRANTS.get(action)
        if grant is None:
            raise ProjectAccessDenied("PROJECT_ACTION_NOT_SUPPORTED_BY_BACKEND")
        if (
            self._caller_verifier is None
            or self._session_verifier is None
            or self._service_verifier is None
            or self._project_verifier is None
            or invocation.service_evidence is None
        ):
            raise ProjectAccessDenied("PROJECT_BACKEND_AUTH_UNAVAILABLE")
        try:
            service_expires_at = await self._service_verifier.verify_service_connection(
                invocation.service_evidence
            )
            if (
                not isinstance(service_expires_at, datetime)
                or service_expires_at.tzinfo is None
                or service_expires_at <= datetime.now(UTC)
            ):
                raise ProjectAccessDenied("PROJECT_SERVICE_IDENTITY_INVALID")
            caller = await self._caller_verifier.resolve_current_authenticated(
                invocation.caller_evidence
            )
            if not isinstance(caller, CurrentAuthenticatedCaller):
                raise ProjectAccessDenied("CALLER_NOT_AUTHENTICATED")
            now = datetime.now(UTC)
            if (
                not isinstance(caller.user_id, UUID)
                or caller.authentication_method not in {"oauth", "local_login"}
                or not isinstance(caller.credential_expires_at, datetime)
                or caller.credential_expires_at.tzinfo is None
                or caller.credential_expires_at <= now
            ):
                raise ProjectAccessDenied("CALLER_NOT_AUTHENTICATED")
            # A4 `project_permit.decision_version` is a SHA-256 string,
            # independent of the AgentSession integer row.version. Never
            # infer Project ownership/membership from Session access alone.
            project = await self._project_verifier.verify_current_project(
                caller, invocation.project_id
            )
            if (
                not isinstance(project, VerifiedProjectAccess)
                or project.project_id != invocation.project_id
                or project.caller_user_id != caller.user_id
                or not valid_project_revision(project.decision_version)
                or project.owner_scope not in {"team", "project"}
                or not isinstance(project.owner_id, UUID)
                or (project.owner_scope == "project" and project.owner_id != invocation.project_id)
                or "use_resources" not in project.permissions
            ):
                raise ProjectAccessDenied("PROJECT_ACCESS_INVALID")
            snapshot = await self._session_verifier.validate_operation(
                caller, invocation.project_id, invocation.session_uuid, grant
            )
            # Two independently queried projections can observe a Project
            # owner transfer/Team revocation between reads. Require stable
            # Backend project access revision across the Session check.
            updated_project = await self._project_verifier.verify_current_project(
                caller, invocation.project_id
            )
            if updated_project != project:
                raise ProjectAccessDenied("PROJECT_ACCESS_STALE")
        except ProjectAccessDenied:
            raise
        except Exception as exc:
            raise ProjectAccessDenied("PROJECT_BACKEND_AUTH_UNAVAILABLE") from exc
        now = datetime.now(UTC)
        if (
            not isinstance(snapshot, ValidatedBackendSession)
            or snapshot.project_id != invocation.project_id
            or snapshot.session_uuid != invocation.session_uuid
            or snapshot.session_uuid.version != 4
            or snapshot.status != "active"
            or grant not in snapshot.granted_operations
            or type(snapshot.version) is not int
            or snapshot.version < 1
            or not isinstance(snapshot.hard_expires_at, datetime)
            or snapshot.hard_expires_at.tzinfo is None
            or snapshot.hard_expires_at <= now
        ):
            raise ProjectAccessDenied("AGENT_SESSION_DENIED")
        expires_at = min(
            service_expires_at,
            caller.credential_expires_at,
            snapshot.hard_expires_at,
            now + _DECISION_TTL,
        )
        if expires_at <= now:
            raise ProjectAccessDenied("PROJECT_DECISION_EXPIRED")
        return ProjectPermit(
            project_id=invocation.project_id,
            actor_id=caller.user_id,
            session_uuid=invocation.session_uuid,
            action=action,
            expires_at=expires_at,
            decision_version=snapshot.version,
            project_access_revision=project.decision_version,
            project_owner_scope=project.owner_scope,
            project_owner_id=project.owner_id,
        )
