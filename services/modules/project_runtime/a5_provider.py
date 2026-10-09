"""A5 resource-ID-bound, read-only trusted provider credential-use consumer.

A5 `ServiceIdentityAuthority` accepts `integrations.use` ONLY for `svc` or
`infrastructure` audience and requires explicit `resource_id`. The accepted
A5 grant does NOT distinguish provider write effects from reads, therefore
this source adapter denies every provider write until a specific elevated
backend operation/grant and effect ledger are accepted. No bearer or secret
is copied into an MCP response, shared Terminal environment, browser or log.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from .a5_authorization import A5Audience, A5AuthenticatedServicePort, A5TrustedDecision
from .authorization import ProjectAction, ProjectInvocation, ProjectRuntimeAuthority
from .credential_use import (
    CredentialLeaseReference,
    ProviderCapabilityError,
    ProviderOperationReceipt,
)
from .integrations import IntegrationProvider, ProjectIntegrationSelector

_MAX_LEASE_TTL = timedelta(seconds=30)


class A5TrustedProviderPort(Protocol):
    """Executes only inside trusted Backend adapter with verified A5 decision."""

    async def acquire_once(
        self,
        invocation: ProjectInvocation,
        *,
        decision: A5TrustedDecision,
        resource_id: UUID,
    ) -> CredentialLeaseReference: ...

    async def execute_once(
        self,
        invocation: ProjectInvocation,
        *,
        decision: A5TrustedDecision,
        lease: CredentialLeaseReference,
        provider: IntegrationProvider,
        capability: str,
        request_id: UUID,
    ) -> ProviderOperationReceipt: ...


class A5ProviderCapability:
    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        integrations: ProjectIntegrationSelector,
        *,
        service: A5AuthenticatedServicePort | None = None,
        provider_backend: A5TrustedProviderPort | None = None,
    ) -> None:
        self.authority = authority
        self.integrations = integrations
        self.service = service
        self.provider_backend = provider_backend

    async def read_once(
        self,
        invocation: ProjectInvocation,
        *,
        resource_id: UUID,
        provider: IntegrationProvider,
        capability: str,
        request_id: UUID,
    ) -> ProviderOperationReceipt:
        if self.service is None or self.provider_backend is None:
            raise ProviderCapabilityError("A5_PROVIDER_BACKEND_UNAVAILABLE")
        if (
            not isinstance(resource_id, UUID)
            or not isinstance(request_id, UUID)
            or request_id.version != 4
            or provider not in {"github", "gitlab", "coolify", "signoz"}
            or not isinstance(capability, str)
            or not 1 <= len(capability) <= 128
            or any(not (ch.isascii() and (ch.isalnum() or ch in "._-")) for ch in capability)
        ):
            raise ProviderCapabilityError("A5_PROVIDER_READ_INVALID")
        action: ProjectAction = (
            "infrastructure.read" if provider in {"coolify", "signoz"} else "svc.read"
        )
        permit = await self.authority.require(invocation, action)
        selection = await self.integrations.select(
            invocation,
            integration_id=resource_id,
            provider=provider,
            operation="read",
        )
        if (
            selection.scope.project_access_revision != permit.project_access_revision
            or selection.scope.effective_project_id != permit.project_id
        ):
            raise ProviderCapabilityError("A5_PROVIDER_PROJECT_SCOPE_STALE")
        audience: A5Audience = "infrastructure" if provider in {"coolify", "signoz"} else "svc"
        # A5 Backend requires the source-owned fingerprint of the EXACT
        # resource-specific operation, not the preceding Gateway metadata
        # authorization. Different audiences need separate signed proofs.
        fingerprint = hashlib.sha256(
            json.dumps(
                [
                    "provider-read-v1",
                    str(permit.project_id),
                    str(permit.session_uuid),
                    str(request_id),
                    str(resource_id),
                    provider,
                    capability,
                    "read",
                ],
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).hexdigest()
        try:
            async with asyncio.timeout(10.0):
                decision = await self.service.consume_current_operation(
                    invocation,
                    expected_audience=audience,
                    expected_operation="integrations.use",
                    expected_resource_id=resource_id,
                    expected_fingerprint=fingerprint,
                    expected_correlation_id=request_id,
                )
        except Exception as exc:
            raise ProviderCapabilityError("A5_PROVIDER_SERVICE_IDENTITY_UNAVAILABLE") from exc
        now = datetime.now(UTC)
        if (
            not isinstance(decision, A5TrustedDecision)
            or decision.project_id != permit.project_id
            or decision.actor_id != permit.actor_id
            or decision.agent_session_uuid != permit.session_uuid
            or decision.agent_session_version != permit.decision_version
            or decision.project_access_revision != permit.project_access_revision
            or decision.resource_id != resource_id
            or decision.operation != "integrations.use"
            or decision.correlation_id != request_id
            or decision.audience != audience
            or not isinstance(decision.service_id, UUID)
            or decision.service_id.version != 4
            or not isinstance(decision.expires_at, datetime)
            or decision.expires_at.tzinfo is None
            or decision.expires_at <= now
        ):
            raise ProviderCapabilityError("A5_PROVIDER_SERVICE_DECISION_INVALID")
        try:
            async with asyncio.timeout(10.0):
                lease = await self.provider_backend.acquire_once(
                    invocation,
                    decision=decision,
                    resource_id=resource_id,
                )
        except Exception as exc:
            raise ProviderCapabilityError("A5_PROVIDER_LEASE_OUTCOME_UNKNOWN") from exc
        if (
            not isinstance(lease, CredentialLeaseReference)
            or lease.project_id != permit.project_id
            or lease.resource_id != resource_id
            or lease.kind != "integration"
            or not isinstance(lease.lease_id, UUID)
            or not isinstance(lease.expires_at, datetime)
            or lease.expires_at.tzinfo is None
            or not now < lease.expires_at <= now + _MAX_LEASE_TTL
        ):
            raise ProviderCapabilityError("A5_PROVIDER_LEASE_INVALID")
        # Authorizer must revalidate Project/Team membership after potential
        # provider/secret rotation and before delegated external SDK action.
        fresh = await self.authority.require(invocation, action)
        if (
            fresh.project_id != permit.project_id
            or fresh.actor_id != permit.actor_id
            or fresh.session_uuid != permit.session_uuid
            or fresh.project_access_revision != permit.project_access_revision
            or fresh.decision_version != permit.decision_version
            or fresh.project_owner_scope != permit.project_owner_scope
            or fresh.project_owner_id != permit.project_owner_id
            or datetime.now(UTC) >= min(lease.expires_at, fresh.expires_at, decision.expires_at)
        ):
            raise ProviderCapabilityError("A5_PROVIDER_PERMISSION_CHANGED")
        try:
            async with asyncio.timeout(60.0):
                receipt = await self.provider_backend.execute_once(
                    invocation,
                    decision=decision,
                    lease=lease,
                    provider=provider,
                    capability=capability,
                    request_id=request_id,
                )
        except Exception as exc:
            raise ProviderCapabilityError("A5_PROVIDER_OUTCOME_UNKNOWN") from exc
        if (
            not isinstance(receipt, ProviderOperationReceipt)
            or receipt.project_id != permit.project_id
            or receipt.resource_id != resource_id
            or receipt.request_id != request_id
            or receipt.provider != provider
            or receipt.capability != capability
            or receipt.operation != "read"
            or receipt.state != "recorded"
        ):
            raise ProviderCapabilityError("A5_PROVIDER_RESULT_UNVERIFIED")
        return receipt

    async def write_once(self, *_args: object, **_kwargs: object) -> None:
        # A5 `integrations.use` would not narrow an external mutation; using
        # its read grant for write would be an unauthorized privilege widening.
        raise ProviderCapabilityError("A5_PROVIDER_WRITE_GRANT_UNAVAILABLE")
