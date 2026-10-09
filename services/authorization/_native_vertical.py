"""A6 private signed Project-owned Reverse/Ghidra import controller.

Native evidence is verified by a distinct configured trusted verifier.
Ghidra does not become a Platform Project, a Files root, or a credential
holder. No native artifact/file delete or public MCP/REST endpoint is added.
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
from projects._native_import_ledger import (
    GhidraObservation,
    NativeImport,
    NativeImportLedger,
    NativeProject,
)

from ._service_identity import ServiceAuthorizationDecision
from ._service_transport import PrivateServiceAuthorizationController, ServiceAuthorizeInput


class NativeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_uuid: UUID

    @field_validator("operation_uuid")
    @classmethod
    def _uuid4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("native operation UUID must be v4")
        return value


class NativeProjectRegistration(NativeCommand):
    native_project_key: str = Field(min_length=1, max_length=256)


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

    @field_validator("idempotency_key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not value.isascii() or not value.isprintable():
            raise ValueError("native import key must be printable ASCII")
        return value

    @field_validator("native_project_id", "file_object_id")
    @classmethod
    def _id(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("native mapping and source File must have UUIDv4 IDs")
        return value


class NativeImportTransition(NativeCommand):
    import_uuid: UUID
    expected_version: int = Field(ge=1)
    phase: Literal["dispatch", "unknown", "cancel", "cleanup"]

    @field_validator("import_uuid")
    @classmethod
    def _id(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("import UUID must be v4")
        return value


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


class NativeProjectReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    project_id: UUID
    native_project_id: UUID
    native_project_key: str
    revision: int = Field(ge=1)
    enabled: bool


class NativeImportReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
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
        "reserved",
        "dispatched",
        "succeeded",
        "unknown",
        "confirmed_absent",
        "cancelled",
    ]
    cleanup_state: str
    revision: int = Field(ge=1)


def native_fingerprint(command: NativeCommand) -> str:
    """Canonical body/digest across signed Backend/Reverse protocol v2."""
    doc = {
        "protocol": "native-project-import-v2",
        "phase": type(command).__name__,
        "body": command.model_dump(mode="json"),
    }
    return hashlib.sha256(
        json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _project(row: NativeProject) -> NativeProjectReceipt:
    return NativeProjectReceipt(
        project_id=row.project_id,
        native_project_id=row.id,
        native_project_key=row.native_project_key,
        revision=row.version,
        enabled=row.enabled,
    )


def _import(row: NativeImport) -> NativeImportReceipt:
    if row.state not in {
        "reserved",
        "dispatched",
        "succeeded",
        "unknown",
        "confirmed_absent",
        "cancelled",
    }:
        raise AccessDenied("native import persisted an unsupported state")
    return NativeImportReceipt(
        project_id=row.project_id,
        import_uuid=row.import_uuid,
        operation_uuid=row.operation_uuid,
        native_project_id=row.native_project_id,
        file_object_id=row.source_file_object_id,
        source_file_version=row.source_file_version,
        source_sha256=row.source_content_sha256,
        size_bytes=row.source_size_bytes,
        auto_analyze=row.auto_analyze,
        native_artifact_id=row.native_artifact_id,
        result_sha256=row.result_sha256,
        status=row.state,  # type: ignore[arg-type]
        cleanup_state=row.cleanup_state,
        revision=row.version,
    )


class SignedNativeImportAuthority:
    """All phases require separately consumed signed service-human proof."""

    def __init__(
        self,
        auth: PrivateServiceAuthorizationController,
        ledger: NativeImportLedger,
    ) -> None:
        self.auth = auth
        self.ledger = ledger

    async def _consume(
        self,
        tx: AsyncSession,
        proof: ServiceAuthorizeInput,
        command: NativeCommand,
        *,
        peer: object,
    ) -> ServiceAuthorizationDecision:
        if (
            proof.intent.operation != "analysis.import"
            or proof.intent.target_audience != "reverse"
            or proof.intent.resource_id is not None
            or proof.intent.operation_uuid != command.operation_uuid
            or proof.intent.payload_sha256 != native_fingerprint(command)
        ):
            raise AccessDenied("signed Reverse operation does not bind full body")
        return await self.auth.consume_in_transaction(
            tx,
            proof,
            peer_evidence=peer,
        )

    async def register_native_project(
        self,
        proof: ServiceAuthorizeInput,
        command: NativeProjectRegistration,
        *,
        peer_evidence: object,
        native_project_evidence: object,
    ) -> NativeProjectReceipt:
        async with self.ledger.app.db.transaction() as tx:
            decision = await self._consume(tx, proof, command, peer=peer_evidence)
            native = await self.ledger.register_native_project(
                tx,
                decision,
                native_project_key=command.native_project_key,
                evidence=native_project_evidence,
            )
            return _project(native)

    async def claim(
        self,
        proof: ServiceAuthorizeInput,
        command: NativeImportClaimCommand,
        *,
        peer_evidence: object,
    ) -> NativeImportReceipt:
        async with self.ledger.app.db.transaction() as tx:
            decision = await self._consume(tx, proof, command, peer=peer_evidence)
            record = await self.ledger.claim(
                tx,
                decision,
                native_project_id=command.native_project_id,
                file_object_id=command.file_object_id,
                expected_file_version=command.source_file_version,
                source_sha256=command.source_sha256,
                source_size_bytes=command.size_bytes,
                auto_analyze=command.auto_analyze,
                idempotency_key=command.idempotency_key,
                operation_uuid=command.operation_uuid,
                request_fingerprint=proof.intent.fingerprint(),
                ttl_seconds=command.ttl_seconds,
            )
            return _import(record)

    async def transition(
        self,
        proof: ServiceAuthorizeInput,
        command: NativeImportTransition,
        *,
        peer_evidence: object,
    ) -> NativeImportReceipt:
        async with self.ledger.app.db.transaction() as tx:
            decision = await self._consume(tx, proof, command, peer=peer_evidence)
            existing = await self.ledger.inspect_operation(tx, decision, command.operation_uuid)
            if existing is None or existing.import_uuid != command.import_uuid:
                raise AccessDenied("Reverse operation does not own native import")
            if command.phase == "dispatch":
                result = await self.ledger.mark_dispatched(
                    tx,
                    decision,
                    command.import_uuid,
                    expected_version=command.expected_version,
                )
            elif command.phase == "unknown":
                result = await self.ledger.mark_unknown(
                    tx,
                    decision,
                    command.import_uuid,
                    expected_version=command.expected_version,
                )
            elif command.phase == "cancel":
                result = await self.ledger.cancel_reserved(
                    tx,
                    decision,
                    command.import_uuid,
                    expected_version=command.expected_version,
                )
            elif command.phase == "cleanup":
                result = await self.ledger.request_source_cleanup(
                    tx,
                    decision,
                    command.import_uuid,
                    expected_version=command.expected_version,
                )
            else:
                raise InvalidInput("unsupported native import phase")
            return _import(result)

    async def reconcile(
        self,
        proof: ServiceAuthorizeInput,
        command: NativeImportResult,
        *,
        peer_evidence: object,
        native_inventory_evidence: object,
    ) -> NativeImportReceipt:
        async with self.ledger.app.db.transaction() as tx:
            decision = await self._consume(tx, proof, command, peer=peer_evidence)
            stored = await self.ledger.inspect_operation(
                tx,
                decision,
                command.operation_uuid,
            )
            if stored is None or stored.import_uuid != command.import_uuid:
                raise AccessDenied("Reverse operation does not own native import")
            actual = GhidraObservation(
                import_uuid=command.import_uuid,
                native_project_id=command.native_project_id,
                source_file_object_id=command.file_object_id,
                source_file_version=command.source_file_version,
                native_artifact_id=command.native_artifact_id,
                confirmed_at=command.confirmed_at,
                result_sha256=command.result_sha256,
                confirmed_absent=command.confirmed_absent,
            )
            resolved = await self.ledger.confirm(
                tx,
                decision,
                actual,
                expected_version=command.expected_version,
                evidence=native_inventory_evidence,
            )
            return _import(resolved)

    async def inspect(
        self,
        proof: ServiceAuthorizeInput,
        command: NativeImportInspect,
        *,
        peer_evidence: object,
    ) -> NativeImportReceipt | None:
        async with self.ledger.app.db.transaction() as tx:
            decision = await self._consume(tx, proof, command, peer=peer_evidence)
            record = await self.ledger.inspect_operation(tx, decision, command.operation_uuid)
            return _import(record) if record is not None else None
