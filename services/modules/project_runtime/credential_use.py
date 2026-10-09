"""Private one-use provider capability from real Backend A3 lease semantics.

Backend owns ResourceCredentialUse.acquire/redeem/execute_with_trusted_adapter.
Its SQL row (not this Python object) decides replay, Project ownership,
AgentSession grant/revoke, provider version and Team membership. No plaintext
SecretStr crosses the SVC/Infrastructure MCP boundary in this consumer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from .authorization import (
    ProjectAction,
    ProjectInvocation,
    ProjectRuntimeAuthority,
)
from .integrations import IntegrationProvider, ProjectIntegrationSelector

ProviderOperation = Literal["read", "write"]
_MAX_CREDENTIAL_TTL = timedelta(seconds=30)  # A3 LEASE_TTL
_AUTH_TYPES: dict[str, frozenset[str]] = {
    "github": frozenset({"personal_token", "github_app"}),
    "gitlab": frozenset({"personal_token", "oauth"}),
    "coolify": frozenset({"api_token"}),
    "signoz": frozenset({"api_token"}),
}


class ProviderCapabilityError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CredentialLeaseReference:
    """Matches A3 CredentialLease metadata; contains no credential bytes."""

    lease_id: UUID
    resource_id: UUID
    project_id: UUID
    kind: Literal["integration"]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderOperationReceipt:
    """Non-secret result; Backend must persist outcome before claiming success."""

    resource_id: UUID
    project_id: UUID
    operation: ProviderOperation
    provider: IntegrationProvider
    capability: str
    request_id: UUID
    state: Literal["recorded", "outcome_unknown"]
    # `recorded` must be a durable, idempotent backend result, not just
    # a successful HTTP/SDK return from an external provider.


class BackendCredentialUsePort(Protocol):
    async def acquire(
        self, invocation: ProjectInvocation, *, resource_id: UUID
    ) -> CredentialLeaseReference: ...

    async def execute_once(
        self,
        invocation: ProjectInvocation,
        *,
        lease: CredentialLeaseReference,
        provider: IntegrationProvider,
        capability: str,
        operation: ProviderOperation,
        request_id: UUID,
    ) -> ProviderOperationReceipt: ...


class ProjectProviderCapability:
    """Never turns a Project UUID or alias into a credential or provider token."""

    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        integrations: ProjectIntegrationSelector,
        backend: BackendCredentialUsePort | None = None,
    ) -> None:
        self._authority = authority
        self._integrations = integrations
        self._backend = backend

    async def execute(
        self,
        invocation: ProjectInvocation,
        *,
        resource_id: UUID,
        provider: IntegrationProvider,
        capability: str,
        operation: ProviderOperation,
        request_id: UUID,
    ) -> ProviderOperationReceipt:
        # There is no fallback to legacy personal token/account or global alias.
        if self._backend is None:
            raise ProviderCapabilityError("PROJECT_CREDENTIAL_PORT_UNAVAILABLE")
        if (
            not isinstance(request_id, UUID)
            or request_id.version != 4
            or not isinstance(resource_id, UUID)
            or not capability
            or len(capability) > 128
            or any(not (ch.isascii() and (ch.isalnum() or ch in "._-")) for ch in capability)
        ):
            raise ProviderCapabilityError("PROJECT_PROVIDER_OPERATION_INVALID")
        if provider not in {"github", "gitlab", "coolify", "signoz"}:
            raise ProviderCapabilityError("PROJECT_PROVIDER_UNKNOWN")
        if operation not in {"read", "write"}:
            raise ProviderCapabilityError("PROJECT_PROVIDER_OPERATION_INVALID")
        if provider in {"coolify", "signoz"} and operation != "read":
            raise ProviderCapabilityError("PROJECT_PROVIDER_WRITE_UNAVAILABLE")
        # Selection/lease acquisition are pre-dispatch: an unavailable Project
        # resource is not an ambiguous external write. Only after execute_once
        # begins may the provider outcome be unknown.
        try:
            selected = await self._integrations.select(
                invocation, integration_id=resource_id, provider=provider, operation=operation
            )
        except Exception as exc:
            raise ProviderCapabilityError("PROJECT_PROVIDER_SELECTION_DENIED") from exc
        if selected.credential_type not in _AUTH_TYPES[provider]:
            raise ProviderCapabilityError("PROJECT_PROVIDER_AUTH_TYPE_INVALID")
        grant: ProjectAction = (
            "svc.write"
            if operation == "write"
            else "infrastructure.read"
            if provider in {"coolify", "signoz"}
            else "svc.read"
        )
        permit = await self._authority.require(invocation, grant)
        issued_at = datetime.now(UTC)
        try:
            async with asyncio.timeout(10.0):
                lease = await self._backend.acquire(invocation, resource_id=resource_id)
        except Exception as exc:
            raise ProviderCapabilityError("PROJECT_CREDENTIAL_LEASE_UNAVAILABLE") from exc
        if (
            not isinstance(lease, CredentialLeaseReference)
            or lease.kind != "integration"
            or lease.resource_id != selected.resource_id
            or lease.project_id != permit.project_id
            or not isinstance(lease.lease_id, UUID)
            or not isinstance(lease.expires_at, datetime)
            or lease.expires_at.tzinfo is None
            or not issued_at < lease.expires_at <= issued_at + _MAX_CREDENTIAL_TTL
        ):
            raise ProviderCapabilityError("PROJECT_CREDENTIAL_LEASE_INVALID")
        # Refresh the independently authorized actor/Project/Session grant
        # immediately before irreversible provider execution. The Backend
        # redemption port must ALSO verify membership/lease/revoke atomically.
        refreshed = await self._authority.require(invocation, grant)
        if (
            refreshed.actor_id != permit.actor_id
            or refreshed.project_access_revision != permit.project_access_revision
            or datetime.now(UTC) >= min(lease.expires_at, refreshed.expires_at)
        ):
            raise ProviderCapabilityError("PROJECT_CREDENTIAL_LEASE_EXPIRED")
        try:
            async with asyncio.timeout(60.0):
                recorded = await self._backend.execute_once(
                    invocation,
                    lease=lease,
                    provider=provider,
                    capability=capability,
                    operation=operation,
                    request_id=request_id,
                )
        except Exception as exc:
            # Provider may have committed despite lost transport response.
            # Never automatically redeem another lease or replay its command.
            raise ProviderCapabilityError("PROJECT_PROVIDER_OUTCOME_UNKNOWN") from exc
        if (
            not isinstance(recorded, ProviderOperationReceipt)
            or recorded.project_id != invocation.project_id
            or recorded.resource_id != resource_id
            or recorded.request_id != request_id
            or recorded.provider != provider
            or recorded.capability != capability
            or recorded.operation != operation
            or recorded.state != "recorded"
        ):
            raise ProviderCapabilityError("PROJECT_PROVIDER_OUTCOME_UNKNOWN")
        return recorded
