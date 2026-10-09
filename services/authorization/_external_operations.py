"""Durable unknown-outcome protection for private provider writes.

An external dispatcher marks 'dispatched' BEFORE sending a provider request.
A timeout or crash after dispatch forbids automatic replay until reconciliation.
This is not an activated service transport.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_errors import AccessDenied, Conflict, InvalidInput
from common.platform_ids import AgentSessionUuid, PlatformProjectId
from projects._resource_domain import ResourceKind
from projects._resource_service import ResourceService

from ._platform_application import PlatformApplication
from ._platform_persistence import ExternalOperationRow
from ._project_access import CallerPrincipal
from ._project_sessions import ProjectSessionService
from ._service_identity import CurrentServiceDecisionValidator, ServiceAuthorizationDecision


class ExternalOutcomeUncertain(Conflict):
    code = "external_outcome_unknown"


class TrustedProviderOutcomeVerifier(Protocol):
    def verify_recorded(
        self,
        *,
        decision: ServiceAuthorizationDecision,
        operation_uuid: UUID,
        result_sha256: str,
        evidence: object,
    ) -> bool:
        """Pure verification of a provider/dispatcher durably signed result."""
        ...


@dataclass(frozen=True, slots=True)
class OperationReceipt:
    operation_id: UUID
    status: str
    project_id: PlatformProjectId
    resource_id: UUID
    service_id: UUID
    instance_uuid: UUID
    operation_uuid: UUID
    result_sha256: str | None = None


class ExternalOperationLedger:
    def __init__(
        self,
        application: PlatformApplication,
        sessions: ProjectSessionService,
        resources: ResourceService,
        *,
        signing_key: bytes,
        validator: CurrentServiceDecisionValidator | None = None,
        outcome_verifier: TrustedProviderOutcomeVerifier | None = None,
    ) -> None:
        self.validator = validator
        self.outcome_verifier = outcome_verifier
        self.app = application
        self.sessions = sessions
        self.resources = resources
        self.key = signing_key

    def _digest(self, value: str) -> str:
        return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()

    async def reserve(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        session_uuid: AgentSessionUuid,
        resource_id: UUID,
        *,
        action: str,
        idempotency_key: str,
        request_fingerprint: str,
        operation_uuid: UUID,
        service_proof: ServiceAuthorizationDecision,
    ) -> OperationReceipt:
        if not (
            1 <= len(idempotency_key) <= 128
            and idempotency_key.isascii()
            and idempotency_key.isprintable()
        ):
            raise InvalidInput("external operation requires bounded idempotency key")
        if not 1 <= len(action) <= 128:
            raise InvalidInput("invalid external operation")
        if (
            not isinstance(operation_uuid, UUID)
            or operation_uuid.version != 4
            or self.validator is None
            or service_proof.actor_id != caller.user_id
            or service_proof.project_id != project_id
            or service_proof.session_uuid != session_uuid
            or service_proof.resource_id != resource_id
            or service_proof.operation != "integrations.use"
            or service_proof.audience not in {"svc", "infrastructure"}
        ):
            raise AccessDenied("service-bound provider operation required")
        await self.validator.verify_live_decision(tx, service_proof)
        if len(request_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in request_fingerprint
        ):
            raise InvalidInput("external request fingerprint must be a canonical SHA-256 digest")
        await self.app.current_user(tx, caller, lock=True)
        await self.sessions.validate_operation(
            tx, caller, project_id, session_uuid, "integrations.use"
        )
        resolved = await self.resources.resolve_for_project(
            tx,
            caller,
            project_id,
            ResourceKind.INTEGRATION,
            resource_id=resource_id,
        )
        # Atomic SQL uniqueness resolves concurrent missing-row races before
        # lookup: a prior committed reservation is returned deterministically.
        candidate_id = uuid4()
        written = await tx.execute(
            insert(ExternalOperationRow)
            .values(
                id=candidate_id,
                actor_id=caller.user_id,
                project_id=project_id,
                session_uuid=session_uuid,
                resource_id=resource_id,
                resource_version=resolved.version,
                service_id=service_proof.service_id,
                instance_uuid=service_proof.instance_uuid,
                operation_uuid=operation_uuid,
                operation=action,
                idempotency_digest=self._digest(idempotency_key),
                request_fingerprint=request_fingerprint,
                status="reserved",
            )
            .on_conflict_do_nothing()
            .returning(ExternalOperationRow.id)
        )
        was_inserted = written.scalar_one_or_none() is not None
        prior = cast(
            ExternalOperationRow | None,
            await tx.scalar(
                select(ExternalOperationRow)
                .where(
                    ExternalOperationRow.actor_id == caller.user_id,
                    ExternalOperationRow.project_id == project_id,
                    ExternalOperationRow.operation == action,
                    ExternalOperationRow.idempotency_digest == self._digest(idempotency_key),
                )
                .with_for_update()
            ),
        )
        if prior is not None:
            if (
                prior.request_fingerprint != request_fingerprint
                or prior.service_id != service_proof.service_id
                or prior.instance_uuid != service_proof.instance_uuid
                or prior.operation_uuid != operation_uuid
                or prior.resource_id != resource_id
                or prior.resource_version != resolved.version
                or prior.session_uuid != session_uuid
            ):
                raise Conflict("external operation key reused for another request")
            if prior.status in {"dispatched", "unknown"}:
                raise ExternalOutcomeUncertain("provider outcome unknown; reconcile before retry")
            if was_inserted:
                self.app._audit(
                    tx,
                    actor=caller.user_id,
                    project=project_id,
                    action="provider.operation_reserved",
                    target=prior.id,
                )
            return OperationReceipt(
                prior.id,
                prior.status,
                project_id,
                prior.resource_id,
                prior.service_id,
                prior.instance_uuid,
                prior.operation_uuid,
                prior.result_sha256,
            )
        raise Conflict("external operation cannot be reserved")

    async def mark_dispatched(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        ticket: OperationReceipt,
        *,
        service_proof: ServiceAuthorizationDecision,
    ) -> None:
        if (
            self.validator is None
            or service_proof.service_id != ticket.service_id
            or service_proof.instance_uuid != ticket.instance_uuid
            or service_proof.resource_id != ticket.resource_id
            or service_proof.project_id != ticket.project_id
            or service_proof.actor_id != caller.user_id
            or service_proof.operation != "integrations.use"
        ):
            raise AccessDenied("verified provider actor/service required for dispatch")
        await self.validator.verify_live_decision(tx, service_proof)
        await self.app.project_allowed(tx, caller, ticket.project_id, for_write=True)
        row = cast(
            ExternalOperationRow | None,
            await tx.scalar(
                select(ExternalOperationRow)
                .where(ExternalOperationRow.id == ticket.operation_id)
                .with_for_update()
            ),
        )
        if (
            row is None
            or row.actor_id != caller.user_id
            or row.project_id != ticket.project_id
            or row.resource_id != ticket.resource_id
            or row.service_id != ticket.service_id
            or row.instance_uuid != ticket.instance_uuid
            or row.operation_uuid != ticket.operation_uuid
            or row.status != "reserved"
        ):
            raise ExternalOutcomeUncertain("external operation cannot be redispatched")
        await self.sessions.validate_operation(
            tx,
            caller,
            ticket.project_id,
            AgentSessionUuid(row.session_uuid),
            "integrations.use",
        )
        resource = await self.resources.resolve_for_project(
            tx,
            caller,
            ticket.project_id,
            ResourceKind.INTEGRATION,
            resource_id=ticket.resource_id,
        )
        if resource.version != row.resource_version:
            raise ExternalOutcomeUncertain("provider resource changed before dispatch")
        row.status = "dispatched"
        row.dispatched_at = datetime.now(UTC)
        self.app._audit(
            tx,
            actor=caller.user_id,
            project=ticket.project_id,
            action="provider.operation_dispatched",
            target=row.id,
        )

    async def settle(
        self,
        tx: AsyncSession,
        ticket: OperationReceipt,
        *,
        service_proof: ServiceAuthorizationDecision,
        succeeded: bool,
        result_sha256: str | None = None,
        evidence: object | None = None,
    ) -> OperationReceipt:
        """Persist only independently verified provider success, else UNKNOWN."""
        if (
            self.validator is None
            or service_proof.service_id != ticket.service_id
            or service_proof.instance_uuid != ticket.instance_uuid
            or service_proof.project_id != ticket.project_id
            or service_proof.resource_id != ticket.resource_id
            or service_proof.operation != "integrations.use"
        ):
            raise AccessDenied("provider settlement requires original verified service")
        await self.validator.verify_live_decision(tx, service_proof)
        if succeeded and (
            result_sha256 is None
            or len(result_sha256) != 64
            or any(c not in "0123456789abcdef" for c in result_sha256)
            or self.outcome_verifier is None
            or evidence is None
            or not self.outcome_verifier.verify_recorded(
                decision=service_proof,
                operation_uuid=ticket.operation_uuid,
                result_sha256=result_sha256,
                evidence=evidence,
            )
        ):
            raise AccessDenied("provider success requires independent durable evidence")
        row = cast(
            ExternalOperationRow | None,
            await tx.scalar(
                select(ExternalOperationRow)
                .where(ExternalOperationRow.id == ticket.operation_id)
                .with_for_update()
            ),
        )
        if (
            row is None
            or row.project_id != ticket.project_id
            or row.resource_id != ticket.resource_id
            or row.service_id != ticket.service_id
            or row.instance_uuid != ticket.instance_uuid
            or row.operation_uuid != ticket.operation_uuid
            or row.actor_id != service_proof.actor_id
            or row.session_uuid != service_proof.session_uuid
            or row.status != "dispatched"
        ):
            raise Conflict("external operation cannot be settled")
        row.status = "succeeded" if succeeded else "unknown"
        row.result_sha256 = result_sha256 if succeeded else None
        row.resolved_at = datetime.now(UTC)
        self.app._audit(
            tx,
            actor=None,
            project=ticket.project_id,
            action="provider.operation_" + row.status,
            target=row.id,
        )
        return OperationReceipt(
            row.id,
            row.status,
            ticket.project_id,
            row.resource_id,
            row.service_id,
            row.instance_uuid,
            row.operation_uuid,
            row.result_sha256,
        )

    async def inspect(
        self,
        tx: AsyncSession,
        service_proof: ServiceAuthorizationDecision,
        *,
        operation_uuid: UUID,
    ) -> OperationReceipt | None:
        """Read authenticated operation state without redispatching provider I/O."""
        if (
            self.validator is None
            or not isinstance(operation_uuid, UUID)
            or operation_uuid.version != 4
            or service_proof.operation != "integrations.use"
            or service_proof.resource_id is None
        ):
            raise AccessDenied("service provider operation proof required")
        await self.validator.verify_live_decision(tx, service_proof)
        row = await tx.scalar(
            select(ExternalOperationRow).where(
                ExternalOperationRow.project_id == service_proof.project_id,
                ExternalOperationRow.actor_id == service_proof.actor_id,
                ExternalOperationRow.session_uuid == service_proof.session_uuid,
                ExternalOperationRow.service_id == service_proof.service_id,
                ExternalOperationRow.instance_uuid == service_proof.instance_uuid,
                ExternalOperationRow.resource_id == service_proof.resource_id,
                ExternalOperationRow.operation_uuid == operation_uuid,
            )
        )
        if row is None:
            return None
        return OperationReceipt(
            row.id,
            row.status,
            service_proof.project_id,
            row.resource_id,
            row.service_id,
            row.instance_uuid,
            row.operation_uuid,
            row.result_sha256,
        )
