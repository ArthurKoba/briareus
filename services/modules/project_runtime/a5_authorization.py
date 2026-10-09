"""Private A5 verified-service authorization consumer; no public transport.

Source: authorization/_service_identity.py. Every request requires Backend-
verified Ed25519 service assertion PLUS Backend-issued delegated human proof,
committed single-use replay ledger and current Project/AgentSession grants.
The transport and key registry are Backend/C1-B2 responsibilities. Neither
Serialized `AuthorizedOperationReceipt` nor a UUID is an executable permit.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime
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
from .backend_access import (
    BackendProjectVerifier,
    CurrentAuthenticatedCaller,
)

A5Audience = Literal["gateway", "files", "terminal", "web", "reverse", "svc", "infrastructure"]
A5Operation = Literal[
    "files.read",
    "files.write",
    "project.metadata.read",
    "terminal.execute",
    "web.access",
    "analysis.import",
    "agents.manage",
    "integrations.use",
    "variables.use",
]

# Exact accepted authorization/_service_identity.ACTION_AUDIENCES pairs.
_ACTION_BINDINGS: dict[ProjectAction, tuple[A5Audience, A5Operation]] = {
    "files.read": ("files", "files.read"),
    "files.write": ("files", "files.write"),
    "terminal.attach": ("terminal", "terminal.execute"),
    "web.internal": ("web", "web.access"),
    "web.remote": ("web", "web.access"),
    "reverse.import": ("reverse", "analysis.import"),
    # Metadata/collection access is not a credential-use lease. A5
    # integrations.use and variables.use require an explicit resource_id;
    # do not pass them to these generic collection selectors.
    "reverse.read": ("gateway", "project.metadata.read"),
    "svc.read": ("gateway", "project.metadata.read"),
    "infrastructure.read": ("gateway", "project.metadata.read"),
    "resources.use": ("gateway", "project.metadata.read"),
}


@dataclass(frozen=True, slots=True)
class A5TrustedDecision:
    """Projection of A5 ServiceAuthorizationDecision AFTER committed consumption.

    Backend must verify the live HMAC-sealed decision in EVERY ledger UoW.
    This non-secret metadata is not a bearer token and does not prove itself.
    """

    service_id: UUID
    actor_id: UUID
    project_id: UUID
    agent_session_uuid: UUID
    audience: A5Audience
    operation: A5Operation
    resource_id: UUID | None
    correlation_id: UUID
    project_access_revision: str
    agent_session_version: int
    session_hard_expires_at: datetime
    expires_at: datetime


class A5AuthenticatedServicePort(Protocol):
    """Authenticated, Backend-owned service caller/replay decision port.

    Each call MUST obtain two NEW signed proofs, consume them in a committed
    SQL UoW using ServiceIdentityAuthority.consume_committed_operation, and
    enforce live enabled User, service key, Team/Project, Session + resource.
    Never return a client-submitted receipt or reuse a consumed assertion.
    """

    async def consume_current_operation(
        self,
        invocation: ProjectInvocation,
        *,
        expected_audience: A5Audience,
        expected_operation: A5Operation,
        expected_resource_id: UUID | None,
        expected_fingerprint: str,
        expected_correlation_id: UUID,
    ) -> A5TrustedDecision: ...


class A5SourceAuthorization(ProjectAccessPort):
    """Transforms independently verified A5 operation + A4 owner into permit."""

    def __init__(
        self,
        *,
        service: A5AuthenticatedServicePort | None = None,
        project: BackendProjectVerifier | None = None,
        caller: ProtocolCaller | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise ValueError("A5 authorization timeout outside bounds")
        self._service = service
        self._project = project
        self._caller = caller
        self.timeout_seconds = timeout_seconds

    async def authorize(
        self, invocation: ProjectInvocation, action: ProjectAction
    ) -> ProjectPermit:
        binding = _ACTION_BINDINGS.get(action)
        if binding is None:
            # `files.manage` and `svc.write` do NOT have accepted A5 actions.
            raise ProjectAccessDenied("A5_OPERATION_NOT_SUPPORTED")
        if self._service is None or self._project is None or self._caller is None:
            raise ProjectAccessDenied("A5_SERVICE_IDENTITY_UNAVAILABLE")
        audience, operation = binding
        if invocation.service_evidence is None or invocation.caller_evidence is None:
            raise ProjectAccessDenied("A5_TWO_PROOFS_REQUIRED")
        scope = invocation.operation_scope
        if (
            scope is None
            or scope.project_id != invocation.project_id
            or scope.agent_session_uuid != invocation.session_uuid
            or scope.action != action
            or not valid_project_revision(scope.fingerprint)
            or scope.resource_id is not None
        ):
            raise ProjectAccessDenied("A5_SIGNED_REQUEST_SCOPE_REQUIRED")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                decision = await self._service.consume_current_operation(
                    invocation,
                    expected_audience=audience,
                    expected_operation=operation,
                    expected_resource_id=None,
                    expected_fingerprint=scope.fingerprint,
                    expected_correlation_id=scope.request_uuid,
                )
                actor = await self._caller.resolve_current_authenticated(invocation.caller_evidence)
                if actor is None:
                    raise ProjectAccessDenied("A5_CALLER_INVALID")
                project = await self._project.verify_current_project(actor, invocation.project_id)
        except ProjectAccessDenied:
            raise
        except Exception as exc:
            raise ProjectAccessDenied("A5_SERVICE_IDENTITY_UNAVAILABLE") from exc
        now = datetime.now(UTC)
        if (
            not isinstance(decision, A5TrustedDecision)
            or not isinstance(actor, CurrentAuthenticatedCaller)
            or decision.service_id.version != 4
            or decision.actor_id != actor.user_id
            or decision.project_id != invocation.project_id
            or decision.agent_session_uuid != invocation.session_uuid
            or decision.agent_session_uuid.version != 4
            or decision.audience != audience
            or decision.operation != operation
            or decision.resource_id is not None
            or decision.correlation_id.version != 4
            or decision.correlation_id != scope.request_uuid
            or not valid_project_revision(decision.project_access_revision)
            or type(decision.agent_session_version) is not int
            or decision.agent_session_version < 1
            or project.project_id != invocation.project_id
            or project.caller_user_id != actor.user_id
            or project.decision_version != decision.project_access_revision
            or "use_resources" not in project.permissions
            or not isinstance(actor.credential_expires_at, datetime)
            or actor.credential_expires_at.tzinfo is None
            or actor.credential_expires_at <= now
            or not isinstance(decision.correlation_id, UUID)
            or decision.correlation_id.version != 4
            or not isinstance(decision.expires_at, datetime)
            or decision.expires_at.tzinfo is None
            or decision.expires_at <= now
            or not isinstance(decision.session_hard_expires_at, datetime)
            or decision.session_hard_expires_at.tzinfo is None
            or decision.session_hard_expires_at <= now
            or decision.expires_at > decision.session_hard_expires_at
        ):
            raise ProjectAccessDenied("A5_SERVICE_DECISION_INVALID")
        return ProjectPermit(
            project_id=invocation.project_id,
            actor_id=decision.actor_id,
            session_uuid=decision.agent_session_uuid,
            action=action,
            expires_at=min(decision.expires_at, actor.credential_expires_at),
            decision_version=decision.agent_session_version,
            project_access_revision=decision.project_access_revision,
            project_owner_scope=project.owner_scope,
            project_owner_id=project.owner_id,
        )


class ProtocolCaller(Protocol):
    async def resolve_current_authenticated(
        self, evidence: object
    ) -> CurrentAuthenticatedCaller | None: ...
