"""A6 signed RuntimeSession source adapter. No OS process is started here.

Accepted `authorization/_runtime_vertical.py` (Backend-only) signs the FULL
phase DTO and executes its SQL CAS inside an independently authenticated
Ed25519 service+human/verified peer UoW. The A6 RuntimeLeaseReceipt DOES NOT
expose the SQL lease_nonce required for heartbeat/job/cleanup. Never mint a
nonce from session UUID or reuse the old local R6 lease as a substitute.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .authorization import ProjectInvocation, ProjectPermit, ProjectRuntimeAuthority


class RuntimeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    operation_uuid: UUID

    @field_validator("operation_uuid")
    @classmethod
    def _uuid4(cls, value: UUID) -> UUID:
        if not isinstance(value, UUID) or value.version != 4:
            raise ValueError("A6 Runtime operation must have UUIDv4")
        return value


class RuntimeOpenCommand(RuntimeCommand):
    runtime_session_uuid: UUID
    instance_uuid: UUID
    kind: Literal["files", "terminal", "web_managed", "web_remote", "reverse"]
    idle_seconds: int = Field(ge=30, le=86400)
    hard_seconds: int = Field(ge=60, le=86400)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("runtime_session_uuid", "instance_uuid")
    @classmethod
    def _uuid(cls, value: UUID) -> UUID:
        if not isinstance(value, UUID) or value.version != 4:
            raise ValueError("A6 Runtime session/instance ID must be UUIDv4")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not value.isascii() or not value.isprintable():
            raise ValueError("A6 Runtime idempotency key must be printable ASCII")
        return value


class RuntimeLeaseCommand(RuntimeCommand):
    runtime_session_uuid: UUID
    expected_version: int = Field(ge=1)
    lease_nonce: UUID | None = None
    phase: Literal["heartbeat", "revoke", "lost", "cleanup", "close", "reconnect"]
    previous_instance_uuid: UUID | None = None


class RuntimeLeaseReceipt(BaseModel):
    """Field-exact A6 SOURCE projection. No nonce, no OS ownership proof."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    runtime_session_uuid: UUID
    project_id: UUID
    agent_session_uuid: UUID
    actor_user_id: UUID
    owner_instance_uuid: UUID
    kind: str
    state: str
    revision: int = Field(ge=1)
    idle_expires_at: datetime
    hard_expires_at: datetime
    lease_expires_at: datetime
    cleanup_state: str


class RuntimeJobCommand(RuntimeCommand):
    runtime_session_uuid: UUID
    runtime_version: int = Field(ge=1)
    lease_nonce: UUID
    idempotency_key: str = Field(min_length=1, max_length=128)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    hard_seconds: int = Field(ge=1, le=86400)


class RuntimeJobTransition(RuntimeCommand):
    runtime_session_uuid: UUID
    runtime_version: int = Field(ge=1)
    lease_nonce: UUID
    job_uuid: UUID
    expected_job_version: int = Field(ge=1)
    target: Literal["running", "succeeded", "failed", "unknown", "cancelled"]
    result_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class RuntimeJobReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    job_uuid: UUID
    runtime_session_uuid: UUID
    project_id: UUID
    status: str
    revision: int = Field(ge=1)
    hard_expires_at: datetime


def runtime_payload_fingerprint(command: RuntimeCommand) -> str:
    """Accepted A6 `runtime_payload_fingerprint` canonical payload SHA."""
    return hashlib.sha256(
        json.dumps(
            {
                "protocol": "project-runtime-v2",
                "phase": type(command).__name__,
                "body": command.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()


class A6RuntimeUnavailable(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class A6RuntimePeer:
    """Service-level attested peer; never a direct MCP JSON value."""

    service_id: UUID
    instance_uuid: UUID
    target_audience: Literal["terminal", "web", "reverse", "files"]
    expires_at: datetime


class A6RuntimePeerPort(Protocol):
    async def verify_runtime_peer(self, evidence: object) -> A6RuntimePeer: ...


class A6SignedRuntimePort(Protocol):
    """Backend SignedRuntimeAuthority must verify FRESH A6 full-body proof.

    Each phase must independently authenticate the registered peer, Ed25519
    assertion, Backend-delegated User/AgentSession, canonical payload SHA and
    consume replay JTIs in its own SQL transaction. A Python receipt is not
    a capability, and the caller must never provide its own service key.
    """

    async def open(
        self,
        invocation: ProjectInvocation,
        *,
        command: RuntimeOpenCommand,
        fingerprint: str,
        peer: A6RuntimePeer,
    ) -> RuntimeLeaseReceipt: ...

    async def transition(
        self,
        invocation: ProjectInvocation,
        *,
        command: RuntimeLeaseCommand,
        fingerprint: str,
        peer: A6RuntimePeer,
    ) -> RuntimeLeaseReceipt: ...

    async def queue_job(
        self,
        invocation: ProjectInvocation,
        *,
        command: RuntimeJobCommand,
        fingerprint: str,
        peer: A6RuntimePeer,
    ) -> RuntimeJobReceipt: ...

    async def transition_job(
        self,
        invocation: ProjectInvocation,
        *,
        command: RuntimeJobTransition,
        fingerprint: str,
        peer: A6RuntimePeer,
    ) -> RuntimeJobReceipt: ...


class A6RuntimeSignedSource:
    """DB intent metadata only. No Terminal/Browser/OS process adoption."""

    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        *,
        peer: A6RuntimePeerPort | None = None,
        backend: A6SignedRuntimePort | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise ValueError("A6 Runtime source timeout invalid")
        self.authority = authority
        self.peer = peer
        self.backend = backend
        self.timeout_seconds = timeout_seconds

    async def _authorize(
        self,
        invocation: ProjectInvocation,
        *,
        action: Literal[
            "files.write", "terminal.attach", "web.internal", "web.remote", "reverse.import"
        ],
        expected_audience: Literal["files", "terminal", "web", "reverse"],
        operation_uuid: UUID,
    ) -> tuple[ProjectPermit, A6RuntimePeer]:
        if self.peer is None or self.backend is None or invocation.service_evidence is None:
            raise A6RuntimeUnavailable("A6_RUNTIME_SIGNED_PEER_UNAVAILABLE")
        scope = invocation.operation_scope
        if (
            scope is None
            or scope.request_uuid != operation_uuid
            or scope.action != action
            or scope.project_id != invocation.project_id
            or scope.agent_session_uuid != invocation.session_uuid
        ):
            raise A6RuntimeUnavailable("A6_RUNTIME_REQUEST_SCOPE_INVALID")
        permit = await self.authority.require(invocation, action)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                peer = await self.peer.verify_runtime_peer(invocation.service_evidence)
        except Exception as exc:
            raise A6RuntimeUnavailable("A6_RUNTIME_PEER_UNAVAILABLE") from exc
        if (
            not isinstance(peer, A6RuntimePeer)
            or peer.target_audience != expected_audience
            or not isinstance(peer.instance_uuid, UUID)
            or peer.instance_uuid.version != 4
            or peer.expires_at.tzinfo is None
            or peer.expires_at <= datetime.now(UTC)
        ):
            raise A6RuntimeUnavailable("A6_RUNTIME_PEER_INVALID")
        return permit, peer

    async def open_intent(
        self,
        invocation: ProjectInvocation,
        *,
        kind: Literal["files", "terminal", "web_managed", "web_remote", "reverse"],
        runtime_session_uuid: UUID,
        operation_uuid: UUID,
        idle_seconds: int,
        hard_seconds: int,
    ) -> RuntimeLeaseReceipt:
        action_map: dict[
            str,
            tuple[
                Literal[
                    "files.write", "terminal.attach", "web.internal", "web.remote", "reverse.import"
                ],
                Literal["files", "terminal", "web", "reverse"],
            ],
        ] = {
            "files": ("files.write", "files"),
            "terminal": ("terminal.attach", "terminal"),
            "web_managed": ("web.internal", "web"),
            "web_remote": ("web.remote", "web"),
            "reverse": ("reverse.import", "reverse"),
        }
        if kind not in action_map:
            raise A6RuntimeUnavailable("A6_RUNTIME_KIND_INVALID")
        action, audience = action_map[kind]
        permit, peer = await self._authorize(
            invocation,
            action=action,
            expected_audience=audience,
            operation_uuid=operation_uuid,
        )
        command = RuntimeOpenCommand(
            operation_uuid=operation_uuid,
            runtime_session_uuid=runtime_session_uuid,
            instance_uuid=peer.instance_uuid,
            kind=kind,
            idle_seconds=idle_seconds,
            hard_seconds=hard_seconds,
            idempotency_key=str(operation_uuid),
        )
        assert self.backend is not None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.backend.open(
                    invocation,
                    command=command,
                    fingerprint=runtime_payload_fingerprint(command),
                    peer=peer,
                )
        except Exception as exc:
            raise A6RuntimeUnavailable("A6_RUNTIME_OPEN_OUTCOME_UNKNOWN") from exc
        if (
            not isinstance(result, RuntimeLeaseReceipt)
            or result.runtime_session_uuid != runtime_session_uuid
            or result.project_id != permit.project_id
            or result.agent_session_uuid != permit.session_uuid
            or result.actor_user_id != permit.actor_id
            or result.owner_instance_uuid != peer.instance_uuid
            or result.kind != kind
            or result.state != "active"
            or result.revision < 1
            or not all(
                isinstance(exp, datetime) and exp.tzinfo is not None
                for exp in (
                    result.idle_expires_at,
                    result.hard_expires_at,
                    result.lease_expires_at,
                )
            )
            or result.lease_expires_at > result.hard_expires_at
            or result.hard_expires_at <= datetime.now(UTC)
        ):
            raise A6RuntimeUnavailable("A6_RUNTIME_OPEN_RECEIPT_INVALID")
        # No lease_nonce in A6 RuntimeLeaseReceipt! This is NOT an OS-owner
        # authorization and CANNOT launch a project-scoped Terminal/Chrome.
        return result

    async def heartbeat_or_job(self, *_args: object, **_kwargs: object) -> None:
        """Missing A6 trusted nonce/instance custody makes CAS unsafe."""
        raise A6RuntimeUnavailable("A6_RUNTIME_SIGNED_NONCE_OWNER_PORT_REQUIRED")
