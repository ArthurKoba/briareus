"""Private signed Backend source port for R7 RuntimeSession/Job ledger phases.

Actual OS processes, browser attachments and native Ghidra assets live in
Runtime and MUST NOT be inferred from these PostgreSQL records. Every phase
has fresh signed service+human proofs bound to full canonical request body.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_errors import AccessDenied, InvalidInput
from projects._runtime_ledger import (
    RuntimeJob,
    RuntimeLease,
    RuntimeLedger,
)

from ._service_identity import ServiceAuthorizationDecision
from ._service_transport import PrivateServiceAuthorizationController, ServiceAuthorizeInput


class RuntimeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    operation_uuid: UUID

    @field_validator("operation_uuid")
    @classmethod
    def _uuid4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("Runtime operation ID must be UUIDv4")
        return value


class RuntimeOpenCommand(RuntimeCommand):
    runtime_session_uuid: UUID
    instance_uuid: UUID
    kind: Literal["files", "terminal", "web_managed", "web_remote", "reverse"]
    idle_seconds: int = Field(ge=30, le=86400)
    hard_seconds: int = Field(ge=60, le=86400)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("instance_uuid", "runtime_session_uuid")
    @classmethod
    def _id(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("Runtime session/instance must be UUIDv4")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not value.isascii() or not value.isprintable():
            raise ValueError("Runtime idempotency key must be printable ASCII")
        return value


class RuntimeLeaseCommand(RuntimeCommand):
    runtime_session_uuid: UUID
    expected_version: int = Field(ge=1)
    lease_nonce: UUID | None = None
    phase: Literal["heartbeat", "revoke", "lost", "cleanup", "close", "reconnect"]
    previous_instance_uuid: UUID | None = None

    @field_validator("runtime_session_uuid", "lease_nonce", "previous_instance_uuid")
    @classmethod
    def _id(cls, value: UUID | None) -> UUID | None:
        if value is not None and value.version != 4:
            raise ValueError("runtime identifier must be UUIDv4")
        return value


class RuntimeJobCommand(RuntimeCommand):
    runtime_session_uuid: UUID
    runtime_version: int = Field(ge=1)
    lease_nonce: UUID
    idempotency_key: str = Field(min_length=1, max_length=128)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    hard_seconds: int = Field(ge=1, le=86400)

    @field_validator("runtime_session_uuid", "lease_nonce")
    @classmethod
    def _id(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("runtime job IDs must be UUIDv4")
        return value


class RuntimeJobTransition(RuntimeCommand):
    runtime_session_uuid: UUID
    runtime_version: int = Field(ge=1)
    lease_nonce: UUID
    job_uuid: UUID
    expected_job_version: int = Field(ge=1)
    target: Literal["running", "succeeded", "failed", "unknown", "cancelled"]
    result_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("runtime_session_uuid", "lease_nonce", "job_uuid")
    @classmethod
    def _id(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("runtime job/session/lease identifiers must be UUIDv4")
        return value


class RuntimeLeaseReceipt(BaseModel):
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


class RuntimeJobReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    job_uuid: UUID
    runtime_session_uuid: UUID
    project_id: UUID
    status: str
    revision: int = Field(ge=1)
    hard_expires_at: datetime


def runtime_payload_fingerprint(command: RuntimeCommand) -> str:
    payload = {
        "protocol": "project-runtime-v2",
        "phase": type(command).__name__,
        "body": command.model_dump(mode="json"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
    ).hexdigest()


def _lease(receipt: RuntimeLease) -> RuntimeLeaseReceipt:
    return RuntimeLeaseReceipt(
        runtime_session_uuid=receipt.runtime_session_uuid,
        project_id=receipt.project_id,
        agent_session_uuid=receipt.agent_session_uuid,
        actor_user_id=receipt.actor_user_id,
        owner_instance_uuid=receipt.owner_instance,
        kind=receipt.kind,
        state=receipt.status,
        revision=receipt.version,
        idle_expires_at=receipt.idle_expires_at,
        hard_expires_at=receipt.hard_expires_at,
        lease_expires_at=receipt.lease_expires_at,
        cleanup_state=receipt.cleanup_state,
    )


def _job(receipt: RuntimeJob) -> RuntimeJobReceipt:
    return RuntimeJobReceipt(
        job_uuid=receipt.job_uuid,
        runtime_session_uuid=receipt.runtime_session_uuid,
        project_id=receipt.project_id,
        status=receipt.status,
        revision=receipt.version,
        hard_expires_at=receipt.hard_expires_at,
    )


class SignedRuntimeAuthority:
    def __init__(
        self,
        auth: PrivateServiceAuthorizationController,
        ledger: RuntimeLedger,
    ) -> None:
        self.auth = auth
        self.ledger = ledger

    async def _consume(
        self,
        tx: AsyncSession,
        proof: ServiceAuthorizeInput,
        command: RuntimeCommand,
        peer: object,
    ) -> ServiceAuthorizationDecision:
        if (
            proof.intent.operation_uuid != command.operation_uuid
            or proof.intent.resource_id is not None
            or proof.intent.payload_sha256 != runtime_payload_fingerprint(command)
        ):
            raise AccessDenied("signed Runtime operation does not bind full body")
        return await self.auth.consume_in_transaction(
            tx,
            proof,
            peer_evidence=peer,
        )

    async def open(
        self,
        proof: ServiceAuthorizeInput,
        command: RuntimeOpenCommand,
        *,
        peer_evidence: object,
    ) -> RuntimeLeaseReceipt:
        if command.instance_uuid != proof.intent.instance_uuid:
            raise AccessDenied("Runtime opening instance does not match signed service")
        async with self.ledger.app.db.transaction() as tx:
            decision = await self._consume(tx, proof, command, peer_evidence)
            value = await self.ledger.open(
                tx,
                decision,
                kind=command.kind,
                instance=command.instance_uuid,
                runtime_session_uuid=command.runtime_session_uuid,
                idle_seconds=command.idle_seconds,
                hard_seconds=command.hard_seconds,
                idempotency_key=command.idempotency_key,
            )
            return _lease(value)

    async def transition(
        self,
        proof: ServiceAuthorizeInput,
        command: RuntimeLeaseCommand,
        *,
        peer_evidence: object,
    ) -> RuntimeLeaseReceipt:
        async with self.ledger.app.db.transaction() as tx:
            decision = await self._consume(tx, proof, command, peer_evidence)
            phase = command.phase
            if phase == "heartbeat":
                if command.lease_nonce is None:
                    raise InvalidInput("Runtime heartbeat requires original lease nonce")
                result = await self.ledger.heartbeat(
                    tx,
                    decision,
                    command.runtime_session_uuid,
                    expected_version=command.expected_version,
                    lease_nonce=command.lease_nonce,
                    instance=decision.instance_uuid,
                )
            elif phase == "revoke":
                result = await self.ledger.revoke(
                    tx,
                    decision,
                    command.runtime_session_uuid,
                    expected_version=command.expected_version,
                )
            elif phase == "lost":
                result = await self.ledger.mark_lost(
                    tx,
                    decision,
                    command.runtime_session_uuid,
                    expected_version=command.expected_version,
                )
            elif phase == "cleanup":
                if command.lease_nonce is None or command.previous_instance_uuid is None:
                    raise InvalidInput("cleanup requires old instance and original nonce")
                result = await self.ledger.confirm_cleanup(
                    tx,
                    decision,
                    command.runtime_session_uuid,
                    expected_version=command.expected_version,
                    owner_instance=command.previous_instance_uuid,
                    lease_nonce=command.lease_nonce,
                )
            elif phase == "reconnect":
                result = await self.ledger.reconnect(
                    tx,
                    decision,
                    command.runtime_session_uuid,
                    expected_version=command.expected_version,
                    new_instance=decision.instance_uuid,
                )
            elif phase == "close":
                result = await self.ledger.close(
                    tx,
                    decision,
                    command.runtime_session_uuid,
                    expected_version=command.expected_version,
                )
            else:
                raise InvalidInput("unsupported Runtime lease transition")
            return _lease(result)

    async def queue_job(
        self,
        proof: ServiceAuthorizeInput,
        command: RuntimeJobCommand,
        *,
        peer_evidence: object,
    ) -> RuntimeJobReceipt:
        async with self.ledger.app.db.transaction() as tx:
            decision = await self._consume(tx, proof, command, peer_evidence)
            result = await self.ledger.queue_job(
                tx,
                decision,
                command.runtime_session_uuid,
                runtime_version=command.runtime_version,
                lease_nonce=command.lease_nonce,
                owner_instance=decision.instance_uuid,
                idempotency_key=command.idempotency_key,
                request_fingerprint=command.request_fingerprint,
                hard_seconds=command.hard_seconds,
            )
            return _job(result)

    async def transition_job(
        self,
        proof: ServiceAuthorizeInput,
        command: RuntimeJobTransition,
        *,
        peer_evidence: object,
    ) -> RuntimeJobReceipt:
        async with self.ledger.app.db.transaction() as tx:
            decision = await self._consume(tx, proof, command, peer_evidence)
            result = await self.ledger.transition_job(
                tx,
                decision,
                command.runtime_session_uuid,
                command.job_uuid,
                runtime_version=command.runtime_version,
                expected_job_version=command.expected_job_version,
                lease_nonce=command.lease_nonce,
                owner_instance=decision.instance_uuid,
                target=command.target,
                result_digest=command.result_digest,
            )
            return _job(result)
