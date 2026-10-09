# ruff: noqa: B008  # FastAPI dependency injection requires Depends in defaults
"""C1-B draft REST/OpenAPI BFF. NEVER mounted without approved C2 caller auth.

An external VerifiedCallerResolver must cryptographically/currently authenticate
the connection and construct CallerPrincipal. No X-User-ID, old username cookie,
Session UUID, unauthenticated service token or fallback is accepted here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agents import AgentIdentity
from authorization._idempotency import CommandOutcome, IdempotentCommandExecutor
from authorization._platform_application import PlatformApplication
from authorization._platform_auth import PlatformAdminBearerAuth
from authorization._project_access import CallerPrincipal
from authorization._project_sessions import (
    AgentSessionView as DomainSessionView,
)
from authorization._project_sessions import (
    ProjectSessionService,
)
from common.platform_errors import AccessDenied, AuthenticationRequired, InvalidInput
from common.platform_ids import AgentIdentityId, AgentSessionUuid, PlatformProjectId, TeamId, UserId
from identity._domain import User, UserRole
from identity._service import IdentityService
from projects import Project
from projects._resource_service import ResourceService
from teams import Team


class VerifiedCallerResolver(Protocol):
    async def resolve(self, request: Request) -> CallerPrincipal | None:
        """Must verify live credential + revoke fence, not a username cookie."""
        ...


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiErrorDetail(ApiModel):
    version: Literal[1] = 1
    code: str
    message: str
    status: int


class ApiErrorEnvelope(ApiModel):
    error: ApiErrorDetail


class UserView(ApiModel):
    user_id: UUID
    username: str
    role: str
    enabled: bool
    credential_version: int

    @classmethod
    def from_user(cls, user: User) -> UserView:
        return cls(
            user_id=user.id,
            username=user.username,
            role=user.role.value,
            enabled=user.enabled,
            credential_version=user.credential_version,
        )


class TeamView(ApiModel):
    team_id: UUID
    name: str
    owner_user_id: UUID
    version: int


class TeamMembershipView(ApiModel):
    team_id: UUID
    user_id: UUID
    active: bool


class ProjectView(ApiModel):
    project_id: UUID
    name: str
    owner_user_id: UUID | None = None
    owner_team_id: UUID | None = None
    version: int


class AgentView(ApiModel):
    agent_id: UUID
    project_id: UUID
    name: str
    parent_agent_id: UUID | None
    enabled: bool
    version: int


class AgentSessionView(ApiModel):
    session_uuid: UUID
    project_id: UUID
    grants: list[str]
    is_elevated: bool
    hard_expires_at: str
    status: str
    version: int
    label: str | None = None
    elevation_policy: str


class CreateTeam(ApiModel):
    name: str = Field(min_length=1, max_length=255)


class AddMember(ApiModel):
    user_id: UUID
    expected_team_version: int = Field(ge=1)


class TransferTeamOwner(ApiModel):
    new_owner_user_id: UUID
    expected_version: int = Field(ge=1)
    confirmed: Literal[True]


class CreateProject(ApiModel):
    name: str = Field(min_length=1, max_length=255)
    owner_team_id: UUID | None = None


class TransferProjectOwner(ApiModel):
    expected_version: int = Field(ge=1)
    confirmed: Literal[True]
    owner_team_id: UUID | None = None
    withdraw_to_personal: bool = False

    def target_team(self) -> TeamId | None:
        if self.withdraw_to_personal == (self.owner_team_id is not None):
            raise InvalidInput("select exactly one Project ownership transfer target")
        return TeamId(self.owner_team_id) if self.owner_team_id else None


class AdminReassignProject(ApiModel):
    expected_version: int = Field(ge=1)
    confirmed: Literal[True]
    new_owner_user_id: UUID | None = None
    new_owner_team_id: UUID | None = None


class CreateAgent(ApiModel):
    name: str = Field(min_length=1, max_length=255)
    parent_agent_id: UUID | None = None


class RenameAgent(ApiModel):
    name: str = Field(min_length=1, max_length=255)
    expected_version: int = Field(ge=1)


class SetAgentEnabled(ApiModel):
    enabled: bool
    expected_version: int = Field(ge=1)
    confirmed: Literal[True]


class Register(ApiModel):
    invitation: str = Field(min_length=10, max_length=512)
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=12, max_length=4096)


class ChangePassword(ApiModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=4096)


class PasswordReset(ApiModel):
    token: str
    new_password: str = Field(min_length=12, max_length=4096)


class SuperuserRole(ApiModel):
    enabled: bool
    confirmed: Literal[True]


class DangerousConfirmation(ApiModel):
    confirmed: Literal[True]


class OpenSession(ApiModel):
    elevation_policy: str = Field("requestable", pattern="^(requestable|fixed)$")
    label: str | None = Field(default=None, min_length=1, max_length=128)


class RequestElevation(ApiModel):
    grants: list[str] = Field(min_length=1, max_length=32)
    seconds: int = Field(300, ge=1, le=300)


class ResolveElevation(ApiModel):
    expected_version: int = Field(ge=1)
    approve: bool
    allowed_grants: list[str] | None = None
    explicit_expansion_confirmation: bool = False


class PermissionView(ApiModel):
    project_id: UUID
    permissions: list[str]


class InvitationView(ApiModel):
    url: str


class ApprovalView(ApiModel):
    request_id: UUID


def _team(value: Team) -> dict[str, object]:
    return TeamView(
        team_id=value.id,
        name=value.name,
        owner_user_id=value.owner_user_id,
        version=value.version,
    ).model_dump(mode="json")


def _project(value: Project) -> dict[str, object]:
    return ProjectView(
        project_id=value.id,
        name=value.name,
        owner_user_id=value.owner_user_id,
        owner_team_id=value.owner_team_id,
        version=value.version,
    ).model_dump(mode="json")


def _agent(value: AgentIdentity) -> dict[str, object]:
    return AgentView(
        agent_id=value.id,
        project_id=value.project_id,
        name=value.name,
        parent_agent_id=value.parent_agent_id,
        enabled=value.enabled,
        version=value.version,
    ).model_dump(mode="json")


def _session(value: DomainSessionView) -> dict[str, object]:
    return AgentSessionView(
        session_uuid=value.session_uuid,
        project_id=value.project_id,
        grants=list(value.grants),
        is_elevated=value.is_elevated,
        hard_expires_at=value.hard_expires_at.isoformat(),
        status=value.status,
        version=value.version,
        label=value.label,
        elevation_policy=value.elevation_policy,
    ).model_dump(mode="json")


def build_unmounted_platform_router(
    *,
    application: PlatformApplication,
    identity: IdentityService,
    sessions: ProjectSessionService,
    commands: IdempotentCommandExecutor,
    principal_resolver: VerifiedCallerResolver,
    resources: ResourceService | None = None,
    local_auth: PlatformAdminBearerAuth | None = None,
) -> APIRouter:
    """Source-only interface; no known safe resolver or C2 mount exists yet."""
    router = APIRouter(
        prefix="/v1/platform",
        tags=["platform-draft"],
        responses={
            400: {"model": ApiErrorEnvelope},
            401: {"model": ApiErrorEnvelope},
            403: {"model": ApiErrorEnvelope},
            404: {"model": ApiErrorEnvelope},
            409: {"model": ApiErrorEnvelope},
            429: {"model": ApiErrorEnvelope},
            503: {"model": ApiErrorEnvelope},
            504: {"model": ApiErrorEnvelope},
        },
    )

    bearer_schema = HTTPBearer(auto_error=False, scheme_name="PlatformAdminBearer")

    async def caller(
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Depends(bearer_schema),
    ) -> CallerPrincipal:
        result = await principal_resolver.resolve(request)
        if result is None or not isinstance(result, CallerPrincipal):
            raise AuthenticationRequired("verified user connection required")
        # Even a replayed Idempotency-Key must not bypass suspension. The
        # future connector must independently prove/revoke the credential.
        async with application.db.transaction() as tx:
            await application.current_user(tx, result)
        return result

    async def execute(
        *,
        key: str | None,
        actor_scope: str,
        project_scope: str,
        operation: str,
        payload: ApiModel,
        callback: Callable[[AsyncSession], Awaitable[CommandOutcome]],
        caller_identity: CallerPrincipal | None = None,
    ) -> dict[str, Any]:
        if key is None:
            raise InvalidInput("Idempotency-Key is required for mutations")

        async def reauthorize(tx: AsyncSession) -> None:
            # A completed idempotent command is not a reusable permission
            # token. Recheck current, authoritative resource scope before
            # decrypting its stored response.
            if caller_identity is None:
                if operation not in {"identity.register", "identity.password.reset"}:
                    raise AuthenticationRequired("verified caller required")
                # Registration/password reset have separate one-use token
                # capabilities; their persisted results contain no credentials.
                return

            user = await application.current_user(tx, caller_identity, lock=True)
            is_admin = user.role is UserRole.SUPERUSER
            action, _, suffix = operation.partition(":")

            if action in {"team.member.add", "team.member.remove", "team.transfer_owner"}:
                team = await application.teams.get(tx, TeamId(UUID(suffix)), lock=True)
                if team is None or (not is_admin and team.owner_user_id != user.id):
                    raise AccessDenied("Team owner permission required")

            elif action == "team.create":
                return

            elif action == "project.create":
                if not isinstance(payload, CreateProject):
                    raise InvalidInput("invalid Project creation contract")
                if payload.owner_team_id is not None:
                    team_id = TeamId(payload.owner_team_id)
                    team = await application.teams.get(tx, team_id, lock=True)
                    if team is None or (
                        not is_admin
                        and not await application.teams.active_member(
                            tx, team_id, caller_identity.user_id
                        )
                    ):
                        raise AccessDenied("Team Project creation permission required")

            elif action == "project.admin_reassign":
                if not is_admin:
                    raise AccessDenied("superuser permission required")

            elif action == "project.transfer_owner":
                project_id = PlatformProjectId(UUID(project_scope))
                row = await application.projects.get(tx, project_id, lock=True)
                if row is None:
                    raise AccessDenied("Project unavailable")
                if not is_admin:
                    if row.owner_user_id is not None:
                        if row.owner_user_id != caller_identity.user_id:
                            raise AccessDenied("personal Project owner required")
                    elif row.owner_team_id is not None:
                        team = await application.teams.get(tx, TeamId(row.owner_team_id), lock=True)
                        if team is None or team.owner_user_id != caller_identity.user_id:
                            raise AccessDenied("Team owner required")
                    else:
                        raise AccessDenied("Project ownership unavailable")

            elif action.startswith(("agent.", "session.")):
                await application.project_allowed(
                    tx, caller_identity, PlatformProjectId(UUID(project_scope))
                )

            elif action in {
                "identity.suspend",
                "identity.restore",
                "identity.superuser",
                "identity.password_reset.issue",
                "identity.delete",
            }:
                if not is_admin:
                    raise AccessDenied("superuser permission required")

            elif action == "identity.invitation.revoke":
                invitation = await identity.repository.get_invitation(tx, UUID(suffix), lock=True)
                if invitation is None or (
                    invitation.created_by_user_id != caller_identity.user_id and not is_admin
                ):
                    raise AccessDenied("invitation permission required")

            elif action in {"identity.invite", "identity.password.change"}:
                return
            else:
                raise InvalidInput("unrecognized idempotent operation")

        result = await commands.execute(
            actor_scope=actor_scope,
            project_scope=project_scope,
            operation=operation,
            key=key,
            payload=payload.model_dump(mode="python"),
            command=callback,
            reauthorize=reauthorize,
        )
        return result.body

    @router.get("/me", response_model=UserView)
    async def me(subject: CallerPrincipal = Depends(caller)) -> object:
        async with application.db.transaction() as tx:
            user = await application.current_user(tx, subject)
            return UserView.from_user(user)

    @router.get("/teams", response_model=list[TeamView])
    async def teams_list(subject: CallerPrincipal = Depends(caller)) -> object:
        async with application.db.transaction() as tx:
            return [_team(x) for x in await application.visible_teams(tx, subject)]

    @router.post("/teams", response_model=TeamView, status_code=201)
    async def team_create(
        body: CreateTeam,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await application.create_team(tx, subject, name=body.name)
            return CommandOutcome(201, _team(value))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope="global",
            operation="team.create",
            payload=body,
            callback=command,
        )

    @router.get("/teams/{team_id}/members", response_model=list[TeamMembershipView])
    async def members(team_id: UUID, subject: CallerPrincipal = Depends(caller)) -> object:
        async with application.db.transaction() as tx:
            return [
                TeamMembershipView(team_id=x.team_id, user_id=x.user_id, active=x.active)
                for x in await application.team_members(tx, subject, TeamId(team_id))
            ]

    @router.post("/teams/{team_id}/members", response_model=TeamMembershipView)
    async def add_member(
        team_id: UUID,
        body: AddMember,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await application.add_team_member(
                tx,
                subject,
                TeamId(team_id),
                UserId(body.user_id),
                expected_version=body.expected_team_version,
            )
            model = TeamMembershipView(team_id=value.team_id, user_id=value.user_id, active=True)
            return CommandOutcome(200, model.model_dump(mode="json"))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope="global",
            operation=f"team.member.add:{team_id}",
            payload=body,
            callback=command,
        )

    @router.delete("/teams/{team_id}/members/{user_id}", response_model=TeamMembershipView)
    async def remove_member(
        team_id: UUID,
        user_id: UUID,
        expected_team_version: int = Header(alias="If-Match-Version", ge=1),
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        payload = AddMember(user_id=user_id, expected_team_version=expected_team_version)

        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await application.remove_team_member(
                tx,
                subject,
                TeamId(team_id),
                UserId(user_id),
                expected_version=expected_team_version,
            )
            model = TeamMembershipView(team_id=value.team_id, user_id=value.user_id, active=False)
            return CommandOutcome(200, model.model_dump(mode="json"))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope="global",
            operation=f"team.member.remove:{team_id}",
            payload=payload,
            callback=command,
        )

    @router.post("/teams/{team_id}/transfer-owner", response_model=TeamView)
    async def team_owner_transfer(
        team_id: UUID,
        body: TransferTeamOwner,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await application.transfer_team_owner(
                tx,
                subject,
                TeamId(team_id),
                UserId(body.new_owner_user_id),
                expected_version=body.expected_version,
            )
            return CommandOutcome(200, _team(value))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope="global",
            operation=f"team.transfer_owner:{team_id}",
            payload=body,
            callback=command,
        )

    @router.get("/projects", response_model=list[ProjectView])
    async def projects_list(subject: CallerPrincipal = Depends(caller)) -> object:
        async with application.db.transaction() as tx:
            return [_project(x) for x in await application.visible_projects(tx, subject)]

    @router.post("/projects", response_model=ProjectView, status_code=201)
    async def project_create(
        body: CreateProject,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await application.create_project(
                tx,
                subject,
                name=body.name,
                team_id=TeamId(body.owner_team_id) if body.owner_team_id else None,
            )
            return CommandOutcome(201, _project(value))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope=str(body.owner_team_id) if body.owner_team_id else "personal",
            operation="project.create",
            payload=body,
            callback=command,
        )

    @router.post("/projects/{project_id}/transfer-owner", response_model=ProjectView)
    async def project_owner_transfer(
        project_id: UUID,
        body: TransferProjectOwner,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        destination = body.target_team()

        async def command(tx: AsyncSession) -> CommandOutcome:
            if destination is None:
                value = await application.withdraw_project_to_personal(
                    tx,
                    subject,
                    PlatformProjectId(project_id),
                    expected_version=body.expected_version,
                )
            else:
                value = await application.transfer_project_to_team(
                    tx,
                    subject,
                    PlatformProjectId(project_id),
                    destination,
                    expected_version=body.expected_version,
                )
            return CommandOutcome(200, _project(value))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope=str(project_id),
            operation="project.transfer_owner",
            payload=body,
            callback=command,
        )

    @router.post("/projects/{project_id}/admin-reassign", response_model=ProjectView)
    async def admin_reassign_project(
        project_id: UUID,
        body: AdminReassignProject,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await application.admin_reassign_project(
                tx,
                subject,
                PlatformProjectId(project_id),
                expected_version=body.expected_version,
                new_owner_user_id=UserId(body.new_owner_user_id)
                if body.new_owner_user_id
                else None,
                new_owner_team_id=TeamId(body.new_owner_team_id)
                if body.new_owner_team_id
                else None,
            )
            return CommandOutcome(200, _project(value))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope=str(project_id),
            operation="project.admin_reassign",
            payload=body,
            callback=command,
        )

    @router.get("/projects/{project_id}/permissions", response_model=PermissionView)
    async def permissions(project_id: UUID, subject: CallerPrincipal = Depends(caller)) -> object:
        async with application.db.transaction() as tx:
            allowed = await application.project_permissions(
                tx, subject, PlatformProjectId(project_id)
            )
            return PermissionView(project_id=project_id, permissions=[p.value for p in allowed])

    @router.get("/projects/{project_id}/agents", response_model=list[AgentView])
    async def agents_list(project_id: UUID, subject: CallerPrincipal = Depends(caller)) -> object:
        async with application.db.transaction() as tx:
            return [
                _agent(x)
                for x in await application.agents_for_project(
                    tx, subject, PlatformProjectId(project_id)
                )
            ]

    @router.post("/projects/{project_id}/agents", response_model=AgentView, status_code=201)
    async def agent_create(
        project_id: UUID,
        body: CreateAgent,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await application.create_agent(
                tx,
                subject,
                PlatformProjectId(project_id),
                name=body.name,
                parent_id=AgentIdentityId(body.parent_agent_id) if body.parent_agent_id else None,
            )
            return CommandOutcome(201, _agent(value))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope=str(project_id),
            operation="agent.create",
            payload=body,
            callback=command,
        )

    @router.patch("/projects/{project_id}/agents/{agent_id}", response_model=AgentView)
    async def agent_rename(
        project_id: UUID,
        agent_id: UUID,
        body: RenameAgent,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await application.rename_agent(
                tx,
                subject,
                PlatformProjectId(project_id),
                AgentIdentityId(agent_id),
                expected_version=body.expected_version,
                name=body.name,
            )
            return CommandOutcome(200, _agent(value))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope=str(project_id),
            operation=f"agent.rename:{agent_id}",
            payload=body,
            callback=command,
        )

    @router.patch("/projects/{project_id}/agents/{agent_id}/state", response_model=AgentView)
    async def agent_change_state(
        project_id: UUID,
        agent_id: UUID,
        body: SetAgentEnabled,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def command(tx: AsyncSession) -> CommandOutcome:
            updated = await application.set_agent_enabled(
                tx,
                subject,
                PlatformProjectId(project_id),
                AgentIdentityId(agent_id),
                expected_version=body.expected_version,
                enabled=body.enabled,
            )
            return CommandOutcome(200, _agent(updated))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope=str(project_id),
            operation=f"agent.state:{agent_id}",
            payload=body,
            callback=command,
        )

    @router.post("/invitations", response_model=InvitationView, status_code=201)
    async def invite(
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        body = ApiModel()

        async def command(tx: AsyncSession) -> CommandOutcome:
            await application.current_user(tx, subject, lock=True)
            url = await identity.issue_registration_invitation(subject.user_id, session=tx)
            application._audit(
                tx,
                actor=subject.user_id,
                project=None,
                action="identity.invitation_created",
                target="registration",
            )
            return CommandOutcome(201, InvitationView(url=url).model_dump(mode="json"))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope="global",
            operation="identity.invite",
            payload=body,
            callback=command,
        )

    @router.post("/registration", response_model=UserView, status_code=201)
    async def register(body: Register, key: str = Header(alias="Idempotency-Key")) -> object:
        # Registration token authenticates ONLY the invitation, never Project
        # access. Rate limiting must be wired at the approved network boundary.
        from authorization.security import token_hash

        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await identity.register(
                invitation=body.invitation,
                username=body.username,
                password=body.password,
                session=tx,
            )
            application._audit(
                tx,
                actor=value.id,
                project=None,
                action="identity.registered",
                target=value.id,
            )
            return CommandOutcome(201, UserView.from_user(value).model_dump(mode="json"))

        return await execute(
            key=key,
            actor_scope="registration:" + token_hash(body.invitation),
            project_scope="global",
            operation="identity.register",
            payload=body,
            callback=command,
        )

    @router.post("/password/change")
    async def password_change(
        body: ChangePassword,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def command(tx: AsyncSession) -> CommandOutcome:
            await identity.change_password(
                subject.user_id,
                current_password=body.current_password,
                new_password=body.new_password,
                session=tx,
            )
            application._audit(
                tx,
                actor=subject.user_id,
                project=None,
                action="identity.password_changed",
                target=subject.user_id,
            )
            return CommandOutcome(200, {"changed": True})

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope="global",
            operation="identity.password.change",
            payload=body,
            callback=command,
        )

    @router.post("/password/reset")
    async def password_reset(
        body: PasswordReset, key: str = Header(alias="Idempotency-Key")
    ) -> object:
        from authorization.security import token_hash

        async def command(tx: AsyncSession) -> CommandOutcome:
            affected_user = await identity.reset_password(body.token, body.new_password, session=tx)
            application._audit(
                tx,
                actor=None,
                project=None,
                action="identity.password_reset",
                target=affected_user.id,
            )
            return CommandOutcome(200, {"changed": True})

        return await execute(
            key=key,
            actor_scope="reset:" + token_hash(body.token),
            project_scope="global",
            operation="identity.password.reset",
            payload=body,
            callback=command,
        )

    @router.post("/users/{user_id}/suspend", response_model=UserView)
    async def suspend(
        user_id: UUID,
        body: DangerousConfirmation,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:

        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await identity.set_suspended(subject.user_id, UserId(user_id), True, session=tx)
            application._audit(
                tx,
                actor=subject.user_id,
                project=None,
                action="identity.suspended",
                target=user_id,
            )
            return CommandOutcome(200, UserView.from_user(value).model_dump(mode="json"))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope="global",
            operation=f"identity.suspend:{user_id}",
            payload=body,
            callback=command,
        )

    @router.post("/users/{user_id}/restore", response_model=UserView)
    async def restore(
        user_id: UUID,
        body: DangerousConfirmation,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:

        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await identity.set_suspended(
                subject.user_id, UserId(user_id), False, session=tx
            )
            application._audit(
                tx,
                actor=subject.user_id,
                project=None,
                action="identity.restored",
                target=user_id,
            )
            return CommandOutcome(200, UserView.from_user(value).model_dump(mode="json"))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope="global",
            operation=f"identity.restore:{user_id}",
            payload=body,
            callback=command,
        )

    @router.post("/users/{user_id}/superuser", response_model=UserView)
    async def set_superuser(
        user_id: UUID,
        body: SuperuserRole,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await identity.set_superuser(
                subject.user_id, UserId(user_id), body.enabled, session=tx
            )
            application._audit(
                tx,
                actor=subject.user_id,
                project=None,
                action="identity.role_changed",
                target=user_id,
                event={"role": value.role.value},
            )
            return CommandOutcome(200, UserView.from_user(value).model_dump(mode="json"))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope="global",
            operation=f"identity.superuser:{user_id}",
            payload=body,
            callback=command,
        )

    @router.post("/users/{user_id}/password-reset", response_model=InvitationView, status_code=201)
    async def issue_password_reset(
        user_id: UUID,
        body: DangerousConfirmation,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:

        async def command(tx: AsyncSession) -> CommandOutcome:
            url = await identity.issue_password_reset(subject.user_id, UserId(user_id), session=tx)
            application._audit(
                tx,
                actor=subject.user_id,
                project=None,
                action="identity.password_reset_issued",
                target=user_id,
            )
            return CommandOutcome(201, InvitationView(url=url).model_dump(mode="json"))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope="global",
            operation=f"identity.password_reset.issue:{user_id}",
            payload=body,
            callback=command,
        )

    @router.delete("/invitations/{invitation_id}")
    async def revoke_invitation(
        invitation_id: UUID,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        body = ApiModel()

        async def command(tx: AsyncSession) -> CommandOutcome:
            await identity.revoke_invitation(subject.user_id, invitation_id, session=tx)
            application._audit(
                tx,
                actor=subject.user_id,
                project=None,
                action="identity.invitation_revoked",
                target=invitation_id,
            )
            return CommandOutcome(200, {"revoked": True})

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope="global",
            operation=f"identity.invitation.revoke:{invitation_id}",
            payload=body,
            callback=command,
        )

    @router.delete("/users/{user_id}", response_model=UserView)
    async def delete_user(
        user_id: UUID,
        body: DangerousConfirmation,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:

        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await application.delete_user(tx, subject, UserId(user_id))
            return CommandOutcome(200, UserView.from_user(value).model_dump(mode="json"))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope="global",
            operation=f"identity.delete:{user_id}",
            payload=body,
            callback=command,
        )

    @router.post(
        "/projects/{project_id}/sessions", response_model=AgentSessionView, status_code=201
    )
    async def session_open(
        project_id: UUID,
        body: OpenSession,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await sessions.open_normal(
                tx,
                subject,
                PlatformProjectId(project_id),
                elevation_policy=body.elevation_policy,
                label=body.label,
            )
            return CommandOutcome(201, _session(value))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope=str(project_id),
            operation="session.open",
            payload=body,
            callback=command,
        )

    @router.post(
        "/projects/{project_id}/sessions/{session_uuid}/elevation",
        response_model=ApprovalView,
        status_code=201,
    )
    async def session_elevation(
        project_id: UUID,
        session_uuid: UUID,
        body: RequestElevation,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await sessions.request_elevation(
                tx,
                subject,
                PlatformProjectId(project_id),
                AgentSessionUuid(session_uuid),
                body.grants,
                seconds=body.seconds,
            )
            return CommandOutcome(201, ApprovalView(request_id=value).model_dump(mode="json"))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope=str(project_id),
            operation=f"session.elevation:{session_uuid}",
            payload=body,
            callback=command,
        )

    @router.post("/projects/{project_id}/approvals/{approval_id}/resolve")
    async def session_resolve(
        project_id: UUID,
        approval_id: UUID,
        body: ResolveElevation,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await sessions.resolve_elevation(
                tx,
                subject,
                PlatformProjectId(project_id),
                approval_id,
                approve=body.approve,
                allowed_grants=body.allowed_grants,
                explicit_expansion_confirmation=body.explicit_expansion_confirmation,
                expected_version=body.expected_version,
            )
            return CommandOutcome(200, {"session": _session(value) if value else None})

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope=str(project_id),
            operation=f"session.resolve:{approval_id}",
            payload=body,
            callback=command,
        )

    @router.post(
        "/projects/{project_id}/sessions/{session_uuid}/revoke", response_model=AgentSessionView
    )
    async def session_revoke(
        project_id: UUID,
        session_uuid: UUID,
        subject: CallerPrincipal = Depends(caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        body = ApiModel()

        async def command(tx: AsyncSession) -> CommandOutcome:
            value = await sessions.revoke(
                tx,
                subject,
                PlatformProjectId(project_id),
                AgentSessionUuid(session_uuid),
            )
            return CommandOutcome(200, _session(value))

        return await execute(
            key=key,
            caller_identity=subject,
            actor_scope=str(subject.user_id),
            project_scope=str(project_id),
            operation=f"session.revoke:{session_uuid}",
            payload=body,
            callback=command,
        )

    # C1-SCOPE resource BFF is part of the same unmounted platform router.
    # It shares the verified principal dependency; never install separately.
    from presentation.resource_api import build_unmounted_resource_router

    if local_auth is not None:
        from presentation.platform_auth_api import build_unmounted_platform_auth_router

        router.include_router(build_unmounted_platform_auth_router(local_auth))

    if resources is not None:
        router.include_router(
            build_unmounted_resource_router(
                resources=resources,
                commands=commands,
                verified_caller=caller,
            )
        )
    from presentation.platform_overview_api import build_unmounted_overview_router

    router.include_router(build_unmounted_overview_router(application, caller))
    from presentation.platform_state_api import build_unmounted_state_router

    router.include_router(build_unmounted_state_router(application, caller))
    from presentation.platform_command_status import (
        build_unmounted_command_status_router,
    )

    router.include_router(build_unmounted_command_status_router(application, caller, resources))
    from presentation.platform_pages_api import build_unmounted_pages_router

    router.include_router(build_unmounted_pages_router(application, caller))
    return router
