"""A6 private signed Project Files quota lifecycle. No public MCP/API mount.

The calling Files runtime independently proves its Ed25519 key, Backend
human delegation and verified TLS/Unix peer. Actual filesystem work and
inode attestations belong to Runtime, NEVER inferred from PostgreSQL rows.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Literal, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_errors import AccessDenied, InvalidInput
from projects._file_quota import FileQuotaLedger, FilesObservation, QuotaReservation

from ._service_identity import ServiceAuthorizationDecision
from ._service_transport import PrivateServiceAuthorizationController, ServiceAuthorizeInput

_RESERVED_FILE = re.compile(r"^\.upload-[0-9a-f]{32}\.tmp$", re.ASCII)


def canonical_project_path(value: str) -> str:
    """Mirror R6 descriptor-based Files path segments, never guess OS root."""
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
    ):
        raise InvalidInput("Project File path must be a nonempty relative path")
    try:
        parts = value.split("/")
        invalid = (
            len(value.encode("utf-8", errors="strict")) > 4096
            or len(parts) > 64
            or any(
                part in {"", ".", ".."}
                or len(part.encode("utf-8", errors="strict")) > 255
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in part)
                or _RESERVED_FILE.fullmatch(part) is not None
                for part in parts
            )
        )
    except UnicodeError as exc:
        raise InvalidInput("Project File path is not valid UTF-8") from exc
    if invalid:
        raise InvalidInput("Project File path is outside confined namespace")
    return "/".join(parts)


def path_fingerprint(path: str) -> str:
    return hashlib.sha256(
        b"files-project-relative-v1\x00" + canonical_project_path(path).encode("utf-8")
    ).hexdigest()


class FilesCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    operation_uuid: UUID

    @field_validator("operation_uuid")
    @classmethod
    def _uuid4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("Files operation_uuid must be UUIDv4")
        return value


class FilesReserve(FilesCommand):
    destination: str = Field(min_length=1, max_length=4096)
    maximum_bytes: int = Field(ge=0, le=100_000_000_000_000)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_file_version: int = Field(ge=0)
    project_access_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("destination")
    @classmethod
    def _path(cls, value: str) -> str:
        return canonical_project_path(value)

    @field_validator("idempotency_key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not value.isascii() or not value.isprintable():
            raise ValueError("Idempotency-Key must be printable ASCII")
        return value


class FilesTransition(FilesCommand):
    reservation_id: UUID
    expected_version: int = Field(ge=1)
    destination: str
    phase: Literal["dispatch", "release", "unknown"]

    @field_validator("reservation_id")
    @classmethod
    def _id(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("reservation_id must be UUIDv4")
        return value

    @field_validator("destination")
    @classmethod
    def _path(cls, value: str) -> str:
        return canonical_project_path(value)


class FilesCommittedObservation(FilesCommand):
    reservation_id: UUID
    expected_version: int = Field(ge=1)
    destination: str
    observed_file_version: int = Field(ge=0)
    observed_size_bytes: int = Field(ge=0, le=100_000_000_000_000)
    observed_inode_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    observed_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    confirmed_absent: bool = False
    confirmed_at: datetime
    source_volume_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    phase: Literal["finalize", "reconcile"]

    @field_validator("destination")
    @classmethod
    def _path(cls, value: str) -> str:
        return canonical_project_path(value)


class FilesInspect(FilesCommand):
    destination: str
    phase: Literal["inspect"] = "inspect"

    @field_validator("destination")
    @classmethod
    def _path(cls, value: str) -> str:
        return canonical_project_path(value)


class FilesRead(FilesCommand):
    path: str = ""
    phase: Literal["read", "list", "metadata"]
    max_bytes: int = Field(default=1048576, ge=0, le=1048576)

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        return canonical_project_path(value) if value else ""


class FilesQuotaReceipt(BaseModel):
    """R6 ProjectQuotaReservation field-compatible superset, NOT file permit."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    reservation_id: UUID
    project_id: UUID
    actor_id: UUID
    session_uuid: UUID
    requested_bytes: int = Field(ge=0)
    operation_uuid: UUID
    destination: str
    expected_sha256: str
    expires_at: datetime
    owner_revision: str
    expected_file_version: int = Field(ge=0)
    reservation_version: int = Field(ge=1)
    status: Literal["reserved", "dispatched", "unknown", "committed", "released"]


class FilesReadPermit(BaseModel):
    """Metadata only: Runtime MUST independently reauthorize before I/O."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    project_id: UUID
    actor_id: UUID
    session_uuid: UUID
    operation_uuid: UUID
    action: Literal["files.read"]
    path: str
    owner_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at: datetime


def files_payload_fingerprint(command: FilesCommand) -> str:
    payload = {
        "protocol": "project-files-transaction-v2",
        "command": type(command).__name__,
        "body": command.model_dump(mode="json"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
    ).hexdigest()


class TrustedFilesStorageObserver(Protocol):
    def validate_observation(
        self,
        *,
        decision: ServiceAuthorizationDecision,
        intent: FilesCommittedObservation,
        path_digest: str,
    ) -> FilesObservation:
        """Pure in-process validation of pre-fetched signed OS receipt.

        No filesystem or network I/O is allowed inside the SQL transaction;
        the trusted supervisor gathers evidence BEFORE command submission.
        """
        ...


class SignedFilesAuthority:
    """All signed phases have an independent committed SQL unit of work."""

    def __init__(
        self,
        auth: PrivateServiceAuthorizationController,
        quota: FileQuotaLedger,
        *,
        observer: TrustedFilesStorageObserver | None = None,
    ) -> None:
        self._auth = auth
        self._quota = quota
        self._observer = observer

    @staticmethod
    def _check_payload(
        proof: ServiceAuthorizeInput,
        command: FilesCommand,
        operation: Literal["files.write", "files.read"],
    ) -> None:
        if (
            proof.intent.target_audience != "files"
            or proof.intent.operation != operation
            or proof.intent.operation_uuid != command.operation_uuid
            or proof.intent.resource_id is not None
            or proof.intent.payload_sha256 != files_payload_fingerprint(command)
        ):
            raise AccessDenied("signed Files command does not match full body")

    async def _consume(
        self,
        tx: AsyncSession,
        proof: ServiceAuthorizeInput,
        command: FilesCommand,
        peer: object,
        *,
        action: Literal["files.write", "files.read"],
    ) -> ServiceAuthorizationDecision:
        self._check_payload(proof, command, action)
        return await self._auth.consume_in_transaction(tx, proof, peer_evidence=peer)

    @staticmethod
    def _receipt(
        record: QuotaReservation,
        *,
        command_destination: str,
        decision: ServiceAuthorizationDecision,
    ) -> FilesQuotaReceipt:
        if record.project_access_revision != decision.decision_version:
            raise AccessDenied("Files reservation owner revision has changed")
        if record.path_digest != path_fingerprint(command_destination):
            raise AccessDenied("Files reservation has different destination")
        if record.state not in {"reserved", "dispatched", "unknown", "committed", "released"}:
            raise AccessDenied("Files reservation state is invalid")
        status = cast(
            Literal["reserved", "dispatched", "unknown", "committed", "released"],
            record.state,
        )
        return FilesQuotaReceipt(
            reservation_id=record.reservation_id,
            project_id=record.project_id,
            actor_id=decision.actor_id,
            session_uuid=decision.session_uuid,
            requested_bytes=record.planned_bytes,
            operation_uuid=record.operation_uuid,
            destination=command_destination,
            expected_sha256=record.expected_content_sha256,
            expires_at=record.expires_at,
            owner_revision=record.project_access_revision,
            expected_file_version=record.expected_file_version,
            reservation_version=record.revision,
            status=status,
        )

    async def reserve(
        self,
        proof: ServiceAuthorizeInput,
        command: FilesReserve,
        *,
        peer_evidence: object,
    ) -> FilesQuotaReceipt:
        async with self._quota.app.db.transaction() as tx:
            decision = await self._consume(tx, proof, command, peer_evidence, action="files.write")
            if command.project_access_revision != decision.decision_version:
                raise AccessDenied("Project permission changed during Files reserve")
            record = await self._quota.reserve(
                tx,
                decision,
                path_digest=path_fingerprint(command.destination),
                planned_bytes=command.maximum_bytes,
                expected_file_version=command.expected_file_version,
                request_fingerprint=proof.intent.fingerprint(),
                expected_content_sha256=command.expected_sha256,
                project_access_revision=decision.decision_version,
                idempotency_key=command.idempotency_key,
                operation_uuid=command.operation_uuid,
            )
            return self._receipt(
                record,
                command_destination=command.destination,
                decision=decision,
            )

    async def issue_read_permit(
        self,
        proof: ServiceAuthorizeInput,
        command: FilesRead,
        *,
        peer_evidence: object,
    ) -> FilesReadPermit:
        if command.phase in {"read", "metadata"} and not command.path:
            raise InvalidInput("File read/metadata requires a path")
        async with self._quota.app.db.transaction() as tx:
            decision = await self._consume(tx, proof, command, peer_evidence, action="files.read")
            return FilesReadPermit(
                project_id=decision.project_id,
                actor_id=decision.actor_id,
                session_uuid=decision.session_uuid,
                operation_uuid=command.operation_uuid,
                action="files.read",
                path=command.path,
                owner_revision=decision.decision_version,
                expires_at=decision.expires_at,
            )

    async def _original_reservation(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        *,
        reservation_id: UUID,
        operation_uuid: UUID,
        destination: str,
    ) -> QuotaReservation:
        record = await self._quota.inspect_operation(tx, decision, operation_uuid)
        if (
            record is None
            or record.reservation_id != reservation_id
            or record.path_digest != path_fingerprint(destination)
        ):
            raise AccessDenied("Files command does not own this reservation/path")
        return record

    async def transition(
        self,
        proof: ServiceAuthorizeInput,
        command: FilesTransition,
        *,
        peer_evidence: object,
    ) -> FilesQuotaReceipt:
        async with self._quota.app.db.transaction() as tx:
            decision = await self._consume(tx, proof, command, peer_evidence, action="files.write")
            original = await self._original_reservation(
                tx,
                decision,
                reservation_id=command.reservation_id,
                operation_uuid=command.operation_uuid,
                destination=command.destination,
            )
            if original.revision != command.expected_version:
                raise AccessDenied("Files command is based on an outdated reservation")
            if command.phase == "dispatch":
                changed = await self._quota.mark_dispatched(
                    tx,
                    decision,
                    command.reservation_id,
                    expected_version=command.expected_version,
                )
            elif command.phase == "release":
                changed = await self._quota.release(
                    tx,
                    decision,
                    command.reservation_id,
                    expected_version=command.expected_version,
                )
            elif command.phase == "unknown":
                changed = await self._quota.mark_unknown(
                    tx,
                    decision,
                    command.reservation_id,
                    expected_version=command.expected_version,
                )
            else:
                raise InvalidInput("unsupported Files quota stage transition")
            return self._receipt(
                changed,
                command_destination=command.destination,
                decision=decision,
            )

    async def complete(
        self,
        proof: ServiceAuthorizeInput,
        command: FilesCommittedObservation,
        *,
        peer_evidence: object,
    ) -> FilesQuotaReceipt:
        # Signed service JWT alone does not prove inode/mount/root custody.
        if self._observer is None:
            raise AccessDenied("C2 verified Files storage observer is not configured")
        async with self._quota.app.db.transaction() as tx:
            decision = await self._consume(tx, proof, command, peer_evidence, action="files.write")
            await self._original_reservation(
                tx,
                decision,
                reservation_id=command.reservation_id,
                operation_uuid=command.operation_uuid,
                destination=command.destination,
            )
            pathname_digest = path_fingerprint(command.destination)
            verified = self._observer.validate_observation(
                decision=decision,
                intent=command,
                path_digest=pathname_digest,
            )
            if (
                not isinstance(verified, FilesObservation)
                or verified.reservation_id != command.reservation_id
                or verified.path_digest != pathname_digest
                or verified.observed_file_version != command.observed_file_version
                or verified.observed_size_bytes != command.observed_size_bytes
                or verified.observed_inode_digest != command.observed_inode_digest
                or verified.observed_content_sha256 != command.observed_content_sha256
                or verified.confirmed_absent != command.confirmed_absent
                or verified.confirmed_at != command.confirmed_at
            ):
                raise AccessDenied("Files OS receipt was not verified by trusted supervisor")
            if command.phase == "finalize":
                changed = await self._quota.finalize(
                    tx,
                    decision,
                    verified,
                    expected_version=command.expected_version,
                )
            elif command.phase == "reconcile":
                changed = await self._quota.reconcile(
                    tx,
                    decision,
                    verified,
                    expected_version=command.expected_version,
                )
            else:
                raise InvalidInput("unknown Files confirmation phase")
            return self._receipt(
                changed,
                command_destination=command.destination,
                decision=decision,
            )

    async def inspect(
        self,
        proof: ServiceAuthorizeInput,
        command: FilesInspect,
        *,
        peer_evidence: object,
    ) -> FilesQuotaReceipt | None:
        """None means NO LEDGER ROW, not proof the file write never happened."""
        async with self._quota.app.db.transaction() as tx:
            decision = await self._consume(tx, proof, command, peer_evidence, action="files.write")
            record = await self._quota.inspect_operation(
                tx,
                decision,
                command.operation_uuid,
            )
            if record is None:
                return None
            return self._receipt(
                record,
                command_destination=command.destination,
                decision=decision,
            )
