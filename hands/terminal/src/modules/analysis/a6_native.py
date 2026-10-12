"""Accepted Backend A6 signed Ghidra ledger adapter (source-only/unmounted).

Native and Platform Project IDs are separate. Each A6 phase signs the FULL
strict command body; no import, worker, artifact delete or replay occurs here.
A signed Backend receipt is not proof that a native Ghidra artifact exists.
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

from modules.project_runtime import ProjectInvocation, ProjectRuntimeAuthority


class NativeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    operation_uuid: UUID

    @field_validator("operation_uuid")
    @classmethod
    def _uuid(cls, value: UUID) -> UUID:
        if not isinstance(value, UUID) or value.version != 4:
            raise ValueError("A6 Native operation must be UUIDv4")
        return value


class NativeImportClaimCommand(NativeCommand):
    native_project_id: UUID
    file_object_id: UUID
    source_file_version: int = Field(ge=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0, le=100_000_000_000_000)
    auto_analyze: bool
    idempotency_key: str = Field(min_length=1, max_length=128)
    ttl_seconds: int = Field(default=1800, ge=60, le=7200)
    phase: Literal["claim"] = "claim"

    @field_validator("native_project_id", "file_object_id")
    @classmethod
    def _uuid(cls, value: UUID) -> UUID:
        if not isinstance(value, UUID) or value.version != 4:
            raise ValueError("Native Project and FileObject IDs must be UUIDv4")
        return value


class NativeImportTransition(NativeCommand):
    import_uuid: UUID
    expected_version: int = Field(ge=1)
    phase: Literal["dispatch", "unknown", "cancel", "cleanup"]


class NativeImportResult(NativeCommand):
    import_uuid: UUID
    native_project_id: UUID
    file_object_id: UUID
    source_file_version: int = Field(ge=1)
    native_artifact_id: str | None = Field(default=None, min_length=1, max_length=256)
    result_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    confirmed_at: datetime
    confirmed_absent: bool = False
    expected_version: int = Field(ge=1)
    phase: Literal["reconcile"] = "reconcile"


class NativeImportInspect(NativeCommand):
    phase: Literal["inspect"] = "inspect"


class NativeImportReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    project_id: UUID
    import_uuid: UUID
    operation_uuid: UUID
    native_project_id: UUID
    file_object_id: UUID
    source_file_version: int = Field(ge=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    auto_analyze: bool
    native_artifact_id: str | None
    result_sha256: str | None
    status: Literal[
        "reserved", "dispatched", "succeeded", "unknown", "confirmed_absent", "cancelled"
    ]
    cleanup_state: str
    revision: int = Field(ge=1)


def native_fingerprint(command: NativeCommand) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "protocol": "native-project-import-v2",
                "phase": type(command).__name__,
                "body": command.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class A6ReversePeer:
    service_id: UUID
    instance_uuid: UUID
    audience: Literal["reverse"]
    expires_at: datetime


class A6ReversePeerPort(Protocol):
    async def verified_reverse_peer(self, evidence: object) -> A6ReversePeer: ...


class A6SignedNativePort(Protocol):
    """Calls Backend SignedNativeImportAuthority with fresh proof per phase.

    Backend rechecks native Project/committed FileObject, Ed25519 registered
    service, Backend delegated User, peer, AgentSession/Team/Project grants,
    JTI, full native_fingerprint() and SQL CAS in each committed transaction.
    Ghidra inventory evidence must be checked by native Backend verifier;
    plain artifact IDs and HTTP success are NOT permitted proof.
    """

    async def claim(
        self,
        invocation: ProjectInvocation,
        *,
        peer: A6ReversePeer,
        command: NativeImportClaimCommand,
        payload_sha256: str,
    ) -> NativeImportReceipt: ...

    async def transition(
        self,
        invocation: ProjectInvocation,
        *,
        peer: A6ReversePeer,
        command: NativeImportTransition,
        payload_sha256: str,
    ) -> NativeImportReceipt: ...

    async def inspect(
        self,
        invocation: ProjectInvocation,
        *,
        peer: A6ReversePeer,
        command: NativeImportInspect,
        payload_sha256: str,
    ) -> NativeImportReceipt | None: ...

    async def reconcile(
        self,
        invocation: ProjectInvocation,
        *,
        peer: A6ReversePeer,
        command: NativeImportResult,
        payload_sha256: str,
        trusted_inventory_evidence: object,
    ) -> NativeImportReceipt: ...


class A6NativeInventoryPort(Protocol):
    """Independent Ghidra worker/supervisor attestation, never caller input."""

    async def verify_current_native_result(
        self,
        invocation: ProjectInvocation,
        *,
        record: NativeImportReceipt,
    ) -> tuple[NativeImportResult, object]: ...


class A6NativeUnavailable(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class A6SignedNativeClient:
    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        *,
        peer: A6ReversePeerPort | None = None,
        backend: A6SignedNativePort | None = None,
        inventory: A6NativeInventoryPort | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise ValueError("A6 Native source timeout invalid")
        self.authority = authority
        self.peer = peer
        self.backend = backend
        self.inventory = inventory
        self.timeout_seconds = timeout_seconds

    async def _context(
        self, invocation: ProjectInvocation, *, operation_uuid: UUID
    ) -> A6ReversePeer:
        if self.peer is None or self.backend is None or invocation.service_evidence is None:
            raise A6NativeUnavailable("A6_NATIVE_SIGNED_TRANSPORT_UNAVAILABLE")
        scope = invocation.operation_scope
        if (
            scope is None
            or scope.request_uuid != operation_uuid
            or scope.action != "reverse.import"
            or scope.project_id != invocation.project_id
            or scope.agent_session_uuid != invocation.session_uuid
        ):
            raise A6NativeUnavailable("A6_NATIVE_OPERATION_SCOPE_INVALID")
        await self.authority.require(invocation, "reverse.import")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                peer = await self.peer.verified_reverse_peer(invocation.service_evidence)
        except Exception as exc:
            raise A6NativeUnavailable("A6_NATIVE_PEER_UNAVAILABLE") from exc
        if (
            not isinstance(peer, A6ReversePeer)
            or peer.audience != "reverse"
            or peer.instance_uuid.version != 4
            or peer.expires_at.tzinfo is None
            or peer.expires_at <= datetime.now(UTC)
        ):
            raise A6NativeUnavailable("A6_NATIVE_PEER_INVALID")
        return peer

    @staticmethod
    def _receipt(
        receipt: NativeImportReceipt,
        *,
        invocation: ProjectInvocation,
        operation_uuid: UUID,
        original: NativeImportReceipt | None = None,
    ) -> NativeImportReceipt:
        if (
            not isinstance(receipt, NativeImportReceipt)
            or receipt.project_id != invocation.project_id
            or receipt.operation_uuid != operation_uuid
            or receipt.import_uuid.version != 4
            or receipt.native_project_id.version != 4
            or receipt.file_object_id.version != 4
            or (
                original is not None
                and (
                    receipt.import_uuid != original.import_uuid
                    or receipt.native_project_id != original.native_project_id
                    or receipt.file_object_id != original.file_object_id
                    or receipt.source_file_version != original.source_file_version
                    or receipt.source_sha256 != original.source_sha256
                    or receipt.size_bytes != original.size_bytes
                    or receipt.revision != original.revision + 1
                )
            )
        ):
            raise A6NativeUnavailable("A6_NATIVE_RECEIPT_SCOPE_INVALID")
        return receipt

    async def claim_intent(
        self,
        invocation: ProjectInvocation,
        *,
        native_project_id: UUID,
        file_object_id: UUID,
        file_version: int,
        source_sha256: str,
        size_bytes: int,
        auto_analyze: bool,
        operation_uuid: UUID,
    ) -> NativeImportReceipt:
        peer = await self._context(invocation, operation_uuid=operation_uuid)
        command = NativeImportClaimCommand(
            operation_uuid=operation_uuid,
            native_project_id=native_project_id,
            file_object_id=file_object_id,
            source_file_version=file_version,
            source_sha256=source_sha256,
            size_bytes=size_bytes,
            auto_analyze=auto_analyze,
            idempotency_key=str(operation_uuid),
        )
        assert self.backend is not None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                receipt = await self.backend.claim(
                    invocation,
                    peer=peer,
                    command=command,
                    payload_sha256=native_fingerprint(command),
                )
        except Exception as exc:
            raise A6NativeUnavailable("A6_NATIVE_CLAIM_OUTCOME_UNKNOWN") from exc
        self._receipt(receipt, invocation=invocation, operation_uuid=operation_uuid)
        if (
            receipt.status != "reserved"
            or receipt.native_project_id != native_project_id
            or receipt.file_object_id != file_object_id
            or receipt.source_file_version != file_version
            or receipt.source_sha256 != source_sha256
            or receipt.size_bytes != size_bytes
            or receipt.auto_analyze is not auto_analyze
        ):
            raise A6NativeUnavailable("A6_NATIVE_CLAIM_RECEIPT_INVALID")
        return receipt

    async def inspect(
        self, invocation: ProjectInvocation, *, operation_uuid: UUID
    ) -> NativeImportReceipt | None:
        peer = await self._context(invocation, operation_uuid=operation_uuid)
        command = NativeImportInspect(operation_uuid=operation_uuid)
        assert self.backend is not None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                receipt = await self.backend.inspect(
                    invocation,
                    peer=peer,
                    command=command,
                    payload_sha256=native_fingerprint(command),
                )
        except Exception as exc:
            raise A6NativeUnavailable("A6_NATIVE_INSPECT_UNAVAILABLE") from exc
        return (
            None
            if receipt is None
            else self._receipt(receipt, invocation=invocation, operation_uuid=operation_uuid)
        )

    async def reconcile_after_verified_inventory(
        self, invocation: ProjectInvocation, *, dispatched: NativeImportReceipt
    ) -> NativeImportReceipt:
        if dispatched.status not in {"dispatched", "unknown"} or self.inventory is None:
            raise A6NativeUnavailable("A6_NATIVE_INVENTORY_REQUIRED")
        peer = await self._context(invocation, operation_uuid=dispatched.operation_uuid)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result, evidence = await self.inventory.verify_current_native_result(
                    invocation,
                    record=dispatched,
                )
        except Exception as exc:
            raise A6NativeUnavailable("A6_NATIVE_INVENTORY_UNAVAILABLE") from exc
        if (
            not isinstance(result, NativeImportResult)
            or result.operation_uuid != dispatched.operation_uuid
            or result.import_uuid != dispatched.import_uuid
            or result.native_project_id != dispatched.native_project_id
            or result.file_object_id != dispatched.file_object_id
            or result.source_file_version != dispatched.source_file_version
            or result.expected_version != dispatched.revision
            or (not result.confirmed_absent and not result.native_artifact_id)
            or result.confirmed_at.tzinfo is None
            or result.confirmed_at > datetime.now(UTC)
        ):
            raise A6NativeUnavailable("A6_NATIVE_INVENTORY_INVALID")
        assert self.backend is not None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                receipt = await self.backend.reconcile(
                    invocation,
                    peer=peer,
                    command=result,
                    payload_sha256=native_fingerprint(result),
                    trusted_inventory_evidence=evidence,
                )
        except Exception as exc:
            raise A6NativeUnavailable("A6_NATIVE_RECONCILE_OUTCOME_UNKNOWN") from exc
        return self._receipt(
            receipt,
            invocation=invocation,
            operation_uuid=dispatched.operation_uuid,
            original=dispatched,
        )

    async def dispatch_intent(
        self,
        invocation: ProjectInvocation,
        *,
        reserved: NativeImportReceipt,
    ) -> NativeImportReceipt:
        """Signed CAS BEFORE irreversible Ghidra worker; no worker here."""
        if reserved.status != "reserved":
            raise A6NativeUnavailable("A6_NATIVE_DISPATCH_REQUIRES_RESERVED")
        peer = await self._context(invocation, operation_uuid=reserved.operation_uuid)
        command = NativeImportTransition(
            operation_uuid=reserved.operation_uuid,
            import_uuid=reserved.import_uuid,
            expected_version=reserved.revision,
            phase="dispatch",
        )
        assert self.backend is not None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.backend.transition(
                    invocation,
                    peer=peer,
                    command=command,
                    payload_sha256=native_fingerprint(command),
                )
        except Exception as exc:
            raise A6NativeUnavailable("A6_NATIVE_DISPATCH_OUTCOME_UNKNOWN") from exc
        self._receipt(
            result,
            invocation=invocation,
            operation_uuid=reserved.operation_uuid,
            original=reserved,
        )
        if result.status != "dispatched":
            raise A6NativeUnavailable("A6_NATIVE_DISPATCH_RECEIPT_INVALID")
        return result

    async def mark_unknown(
        self,
        invocation: ProjectInvocation,
        *,
        dispatched: NativeImportReceipt,
    ) -> None:
        """Persist UNKNOWN after native effect may have started; no replay."""
        if dispatched.status != "dispatched" or self.backend is None:
            return
        try:
            peer = await self._context(invocation, operation_uuid=dispatched.operation_uuid)
            command = NativeImportTransition(
                operation_uuid=dispatched.operation_uuid,
                import_uuid=dispatched.import_uuid,
                expected_version=dispatched.revision,
                phase="unknown",
            )
            async with asyncio.timeout(self.timeout_seconds):
                await self.backend.transition(
                    invocation,
                    peer=peer,
                    command=command,
                    payload_sha256=native_fingerprint(command),
                )
        except Exception:
            # Backend sweep/independent native inventory must reconcile.
            # Never retry, release or delete a potentially imported artifact.
            return
