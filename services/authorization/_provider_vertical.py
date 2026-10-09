"""A6 private SVC read-only provider capability, no general MCP transport.

This is NOT an HTTP proxy and does not export plaintext credentials. The
human and runtime service must independently authenticate, an explicit
resource UUID selects a current Project integration, and a trusted, injected
provider policy/adapter/result verifier decides whether a safe read can run.

No provider write/delete, shell/env injection or direct unaudited credential
exfiltration is available. C2 verifier/provider transport is unconfigured.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from common.platform_errors import AccessDenied
from common.platform_ids import AgentSessionUuid, PlatformProjectId, UserId
from projects._resource_domain import ResourceKind
from projects._resource_service import ResourceService

from ._external_operations import (
    ExternalOperationLedger,
    OperationReceipt,
)
from ._project_access import AuthenticationMethod, CallerPrincipal
from ._resource_leases import (
    CredentialLease,
    CredentialOperationContext,
    CredentialProviderAdapter,
    ResourceCredentialUse,
)
from ._service_identity import ServiceAuthorizationDecision
from ._service_transport import PrivateServiceAuthorizationController, ServiceAuthorizeInput


class ProviderReadCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    operation_uuid: UUID
    resource_id: UUID
    provider: str = Field(min_length=2, max_length=32)
    capability: str = Field(min_length=1, max_length=80)
    idempotency_key: str = Field(min_length=1, max_length=128)
    phase: Literal["read"] = "read"

    @field_validator("operation_uuid", "resource_id")
    @classmethod
    def _uuid4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("provider request/resource identifiers must be UUIDv4")
        return value

    @field_validator("provider", "capability")
    @classmethod
    def _safe_name(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", value):
            raise ValueError("provider/capability name invalid")
        if any(part in value for part in (".write", ".delete", ".admin", ".mutate")):
            raise ValueError("provider read capability must not imply modification")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not value.isascii() or not value.isprintable():
            raise ValueError("Idempotency-Key must be printable ASCII")
        return value


class ProviderInspectCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    operation_uuid: UUID
    resource_id: UUID
    phase: Literal["inspect"] = "inspect"

    @field_validator("operation_uuid", "resource_id")
    @classmethod
    def _uuid4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("provider operation IDs must be UUIDv4")
        return value


class ProviderReadReceipt(BaseModel):
    """An UNKNOWN read is never silently reported as a durable result."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    project_id: UUID
    resource_id: UUID
    operation_uuid: UUID
    state: Literal["recorded", "outcome_unknown", "reserved"]
    result_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # No provider response body, OAuth token or remote URL in source result.


@dataclass(frozen=True, slots=True)
class ProviderReadEvidence:
    operation_uuid: UUID
    resource_id: UUID
    provider: str
    capability: str
    result_sha256: str
    observed_at: datetime
    proof: SecretStr


class ApprovedProviderReadPolicy(Protocol):
    def allows(
        self,
        *,
        provider: str,
        auth_type: str,
        capability: str,
    ) -> bool:
        """Injected immutable provider-specific allowlist, not user's choice."""
        ...


class TrustedProviderReadAdapter(Protocol):
    async def execute_read(
        self,
        credential: SecretStr,
        context: CredentialOperationContext,
        *,
        provider: str,
        capability: str,
        operation_uuid: UUID,
    ) -> ProviderReadEvidence:
        """Service-only approved transport; never shell/env or generic HTTP."""
        ...


class _ReadCredentialAdapter(CredentialProviderAdapter):
    def __init__(
        self,
        adapter: TrustedProviderReadAdapter,
        *,
        provider: str,
        capability: str,
        operation_uuid: UUID,
    ) -> None:
        self.adapter = adapter
        self.provider = provider
        self.capability = capability
        self.operation_uuid = operation_uuid
        self.observed: ProviderReadEvidence | None = None

    async def execute(
        self,
        credential: SecretStr,
        context: CredentialOperationContext,
    ) -> None:
        self.observed = await self.adapter.execute_read(
            credential,
            context,
            provider=self.provider,
            capability=self.capability,
            operation_uuid=self.operation_uuid,
        )


def provider_command_fingerprint(command: ProviderReadCommand | ProviderInspectCommand) -> str:
    body = {
        "protocol": "project-provider-read-v2",
        "command": type(command).__name__,
        "body": command.model_dump(mode="json"),
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


class SignedProviderReadAuthority:
    def __init__(
        self,
        auth: PrivateServiceAuthorizationController,
        resources: ResourceService,
        credentials: ResourceCredentialUse,
        operations: ExternalOperationLedger,
        *,
        policy: ApprovedProviderReadPolicy | None = None,
        provider_adapter: TrustedProviderReadAdapter | None = None,
    ) -> None:
        self.auth = auth
        self.resources = resources
        self.credentials = credentials
        self.operations = operations
        self.policy = policy
        self.provider_adapter = provider_adapter

    @staticmethod
    def _caller(decision: ServiceAuthorizationDecision) -> CallerPrincipal:
        return CallerPrincipal(
            user_id=UserId(decision.actor_id),
            authentication_method=AuthenticationMethod.LOCAL_LOGIN,
            credential_version=decision.actor_credential_version,
            admin_jti_digest=decision.actor_admin_jti_digest,
        )

    @staticmethod
    def _check(
        proof: ServiceAuthorizeInput, command: ProviderReadCommand | ProviderInspectCommand
    ) -> None:
        if (
            proof.intent.operation != "integrations.use"
            or proof.intent.target_audience not in {"svc", "infrastructure"}
            or proof.intent.operation_uuid != command.operation_uuid
            or proof.intent.resource_id != command.resource_id
            or proof.intent.payload_sha256 != provider_command_fingerprint(command)
        ):
            raise AccessDenied("signed provider read proof not bound to operation")

    @staticmethod
    def _receipt(item: OperationReceipt) -> ProviderReadReceipt:
        status = (
            "recorded"
            if item.status == "succeeded"
            else "reserved"
            if item.status == "reserved"
            else "outcome_unknown"
        )
        typed_status = cast(Literal["recorded", "outcome_unknown", "reserved"], status)
        return ProviderReadReceipt(
            project_id=item.project_id,
            resource_id=item.resource_id,
            operation_uuid=item.operation_uuid,
            state=typed_status,
            result_sha256=item.result_sha256 if status == "recorded" else None,
        )

    async def inspect(
        self,
        proof: ServiceAuthorizeInput,
        command: ProviderInspectCommand,
        *,
        peer_evidence: object,
    ) -> ProviderReadReceipt | None:
        self._check(proof, command)
        async with self.resources.application.db.transaction() as tx:
            decision = await self.auth.consume_in_transaction(
                tx, proof, peer_evidence=peer_evidence
            )
            item = await self.operations.inspect(
                tx,
                decision,
                operation_uuid=command.operation_uuid,
            )
            return self._receipt(item) if item is not None else None

    async def execute_read(
        self,
        proof: ServiceAuthorizeInput,
        command: ProviderReadCommand,
        *,
        peer_evidence: object,
    ) -> ProviderReadReceipt:
        """Persist dispatched before trusted I/O; UNKNOWN on any uncertainty."""
        self._check(proof, command)
        if (
            self.policy is None
            or self.provider_adapter is None
            or self.operations.outcome_verifier is None
        ):
            raise AccessDenied("C2 approved provider read port is not configured")

        decision: ServiceAuthorizationDecision
        ticket: OperationReceipt
        lease: CredentialLease
        async with self.resources.application.db.transaction() as tx:
            decision = await self.auth.consume_in_transaction(
                tx, proof, peer_evidence=peer_evidence
            )
            caller = self._caller(decision)
            project = PlatformProjectId(decision.project_id)
            resource = await self.resources.resolve_for_project(
                tx,
                caller,
                project,
                ResourceKind.INTEGRATION,
                resource_id=command.resource_id,
            )
            if (
                resource.provider != command.provider
                or resource.auth_type is None
                or not self.policy.allows(
                    provider=command.provider,
                    auth_type=resource.auth_type,
                    capability=command.capability,
                )
            ):
                raise AccessDenied("provider read capability not approved")
            ticket = await self.operations.reserve(
                tx,
                caller,
                project,
                AgentSessionUuid(decision.session_uuid),
                command.resource_id,
                action=f"{command.provider}.{command.capability}.read",
                idempotency_key=command.idempotency_key,
                request_fingerprint=proof.intent.fingerprint(),
                operation_uuid=command.operation_uuid,
                service_proof=decision,
            )
            lease = await self.credentials.acquire(
                tx,
                caller,
                project,
                AgentSessionUuid(decision.session_uuid),
                kind=ResourceKind.INTEGRATION,
                resource_id=command.resource_id,
                operation_uuid=command.operation_uuid,
                service_proof=decision,
            )
            await self.operations.mark_dispatched(
                tx,
                caller,
                ticket,
                service_proof=decision,
            )

        ticket = replace(ticket, status="dispatched")
        # SQL intent is committed, and the one-use credential is consumed in
        # a SECOND transaction before ever touching external provider I/O.
        # Connection/provenance/TTL/credential revoke is still rechecked.
        adapter = _ReadCredentialAdapter(
            self.provider_adapter,
            provider=command.provider,
            capability=command.capability,
            operation_uuid=command.operation_uuid,
        )
        try:
            await self.credentials.execute_with_trusted_adapter(
                caller,
                AgentSessionUuid(decision.session_uuid),
                lease,
                adapter,
                service_proof=decision,
            )
        except Exception:
            # Never infer an external side effect failed after a timeout.
            # Keep original dispatched ledger; inspect/reconcile before retry.
            return self._receipt(ticket)

        evidence = adapter.observed
        if (
            not isinstance(evidence, ProviderReadEvidence)
            or evidence.operation_uuid != command.operation_uuid
            or evidence.resource_id != command.resource_id
            or evidence.provider != command.provider
            or evidence.capability != command.capability
            or not re.fullmatch(r"[0-9a-f]{64}", evidence.result_sha256)
            or evidence.observed_at.tzinfo is None
            or evidence.observed_at > datetime.now(UTC)
        ):
            return self._receipt(ticket)

        try:
            async with self.resources.application.db.transaction() as tx:
                recorded = await self.operations.settle(
                    tx,
                    ticket,
                    service_proof=decision,
                    succeeded=True,
                    result_sha256=evidence.result_sha256,
                    evidence=evidence,
                )
                return self._receipt(recorded)
        except Exception:
            # A valid HTTP provider reply is not a durably reconciled result.
            return self._receipt(ticket)
