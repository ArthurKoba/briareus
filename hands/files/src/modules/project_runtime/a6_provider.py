"""Private A6 signed provider READ only; no secret/MCP/Terminal export.

Matches accepted `authorization/_provider_vertical.py`. A returned source
receipt has ONLY operation status and SHA, never OAuth/API keys, provider
response payload, shell environment, URL or raw SDK traceback. Actual
provider transport and Backend signed authority remain unconfigured.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .authorization import ProjectInvocation, ProjectPermit, ProjectRuntimeAuthority
from .integrations import IntegrationProvider, ProjectIntegrationSelector


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
    def _uuid(cls, value: UUID) -> UUID:
        if not isinstance(value, UUID) or value.version != 4:
            raise ValueError("A6 provider resource/operation requires UUIDv4")
        return value

    @field_validator("provider", "capability")
    @classmethod
    def _safe_read_name(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", value, re.ASCII):
            raise ValueError("A6 provider capability is invalid")
        if any(part in value for part in (".write", ".delete", ".admin", ".mutate")):
            raise ValueError("A6 provider command cannot imply mutation")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not value.isascii() or not value.isprintable():
            raise ValueError("A6 provider idempotency key must be ASCII")
        return value


class ProviderInspectCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    operation_uuid: UUID
    resource_id: UUID
    phase: Literal["inspect"] = "inspect"


class ProviderReadReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    project_id: UUID
    resource_id: UUID
    operation_uuid: UUID
    state: Literal["recorded", "outcome_unknown", "reserved"]
    result_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def provider_command_fingerprint(
    command: ProviderReadCommand | ProviderInspectCommand,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "protocol": "project-provider-read-v2",
                "command": type(command).__name__,
                "body": command.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class A6ProviderPeer:
    service_id: UUID
    instance_uuid: UUID
    audience: Literal["svc", "infrastructure"]
    expires_at: datetime


class A6ProviderPeerPort(Protocol):
    async def verified_provider_peer(self, evidence: object) -> A6ProviderPeer: ...


class A6SignedProviderPort(Protocol):
    """Uses actual Backend SignedProviderReadAuthority with signed JWT+UoW.

    Backend MUST bind peer instance, full DTO payload SHA, resource UUID and
    trusted approved provider READ policy/credential adapter to one-use lease,
    idempotent outcome ledger and independent result verifier. No generic
    HTTP SDK, Shell process or plain SecretStr leaves that authority.
    """

    async def read(
        self,
        invocation: ProjectInvocation,
        *,
        command: ProviderReadCommand,
        payload_sha256: str,
        peer: A6ProviderPeer,
    ) -> ProviderReadReceipt: ...

    async def inspect(
        self,
        invocation: ProjectInvocation,
        *,
        command: ProviderInspectCommand,
        payload_sha256: str,
        peer: A6ProviderPeer,
    ) -> ProviderReadReceipt | None: ...


class A6ProviderUnavailable(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class A6ProviderReadSource:
    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        integrations: ProjectIntegrationSelector,
        *,
        peer: A6ProviderPeerPort | None = None,
        backend: A6SignedProviderPort | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise ValueError("A6 provider source timeout invalid")
        self.authority = authority
        self.integrations = integrations
        self.peer = peer
        self.backend = backend
        self.timeout_seconds = timeout_seconds

    async def _verified(
        self,
        invocation: ProjectInvocation,
        *,
        resource_id: UUID,
        operation_uuid: UUID,
        provider: IntegrationProvider,
    ) -> tuple[ProjectPermit, A6ProviderPeer]:
        if self.backend is None or self.peer is None or invocation.service_evidence is None:
            raise A6ProviderUnavailable("A6_PROVIDER_SIGNED_TRANSPORT_UNAVAILABLE")
        action = "infrastructure.read" if provider in {"coolify", "signoz"} else "svc.read"
        scope = invocation.operation_scope
        if (
            scope is None
            or scope.request_uuid != operation_uuid
            or scope.resource_id != resource_id
            or scope.action != action
            or scope.project_id != invocation.project_id
            or scope.agent_session_uuid != invocation.session_uuid
        ):
            raise A6ProviderUnavailable("A6_PROVIDER_REQUEST_SCOPE_MISMATCH")
        permit = await self.authority.require(invocation, action)
        expected = "infrastructure" if provider in {"coolify", "signoz"} else "svc"
        try:
            async with asyncio.timeout(self.timeout_seconds):
                peer = await self.peer.verified_provider_peer(invocation.service_evidence)
        except Exception as exc:
            raise A6ProviderUnavailable("A6_PROVIDER_PEER_UNAVAILABLE") from exc
        if (
            not isinstance(peer, A6ProviderPeer)
            or peer.audience != expected
            or not isinstance(peer.instance_uuid, UUID)
            or peer.instance_uuid.version != 4
            or not isinstance(peer.expires_at, datetime)
            or peer.expires_at.tzinfo is None
            or peer.expires_at <= datetime.now(UTC)
        ):
            raise A6ProviderUnavailable("A6_PROVIDER_PEER_INVALID")
        return permit, peer

    async def read_once(
        self,
        invocation: ProjectInvocation,
        *,
        resource_id: UUID,
        operation_uuid: UUID,
        provider: IntegrationProvider,
        capability: str,
    ) -> ProviderReadReceipt:
        permit, peer = await self._verified(
            invocation,
            resource_id=resource_id,
            operation_uuid=operation_uuid,
            provider=provider,
        )
        selected = await self.integrations.select(
            invocation, integration_id=resource_id, provider=provider, operation="read"
        )
        if (
            selected.scope.effective_project_id != permit.project_id
            or selected.scope.project_access_revision != permit.project_access_revision
        ):
            raise A6ProviderUnavailable("A6_PROVIDER_RESOURCE_OWNER_CHANGED")
        command = ProviderReadCommand(
            operation_uuid=operation_uuid,
            resource_id=resource_id,
            provider=provider,
            capability=capability,
            idempotency_key=str(operation_uuid),
        )
        assert self.backend is not None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.backend.read(
                    invocation,
                    command=command,
                    payload_sha256=provider_command_fingerprint(command),
                    peer=peer,
                )
        except Exception as exc:
            raise A6ProviderUnavailable("A6_PROVIDER_OUTCOME_UNKNOWN") from exc
        if (
            not isinstance(result, ProviderReadReceipt)
            or result.project_id != permit.project_id
            or result.resource_id != resource_id
            or result.operation_uuid != operation_uuid
            or (result.state == "recorded" and not result.result_sha256)
        ):
            raise A6ProviderUnavailable("A6_PROVIDER_RECEIPT_INVALID")
        return result

    async def write_once(self, *_args: object, **_kwargs: object) -> None:
        raise A6ProviderUnavailable("A6_PROVIDER_WRITE_ACTION_UNAPPROVED")

    async def inspect_read(
        self,
        invocation: ProjectInvocation,
        *,
        resource_id: UUID,
        operation_uuid: UUID,
        provider: IntegrationProvider,
    ) -> ProviderReadReceipt | None:
        """Read current effect state by ORIGINAL UUID. Never auto-retry."""
        permit, peer = await self._verified(
            invocation,
            resource_id=resource_id,
            operation_uuid=operation_uuid,
            provider=provider,
        )
        command = ProviderInspectCommand(
            operation_uuid=operation_uuid,
            resource_id=resource_id,
        )
        assert self.backend is not None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                receipt = await self.backend.inspect(
                    invocation,
                    command=command,
                    payload_sha256=provider_command_fingerprint(command),
                    peer=peer,
                )
        except Exception as exc:
            raise A6ProviderUnavailable("A6_PROVIDER_INSPECT_UNAVAILABLE") from exc
        if receipt is not None and (
            not isinstance(receipt, ProviderReadReceipt)
            or receipt.project_id != permit.project_id
            or receipt.resource_id != resource_id
            or receipt.operation_uuid != operation_uuid
        ):
            raise A6ProviderUnavailable("A6_PROVIDER_INSPECT_RECEIPT_INVALID")
        # None or reserved/unknown is not proof external provider did nothing.
        return receipt
