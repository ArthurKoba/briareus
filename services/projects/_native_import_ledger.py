"""Project-scoped native Ghidra import intent; native artifacts are permanent.

Files Project paths, bridge Project UUIDs and Ghidra native project IDs are
distinct. A confirmed Ghidra success is recorded without granting any
backend authority to delete native data or a different Project's artifacts.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._platform_application import PlatformApplication
from authorization._service_identity import (
    CurrentServiceDecisionValidator,
    ServiceAuthorizationDecision,
)
from common.platform_errors import AccessDenied, Conflict, InvalidInput
from common.platform_ids import PlatformProjectId

from ._file_quota_persistence import FileObjectRow
from ._native_import_persistence import NativeImportRow, NativeProjectRow


def _now() -> datetime:
    return datetime.now(UTC)


def _opaque_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", name):
        raise InvalidInput("native Ghidra identifier must be an opaque name")
    return name


def _digest(value: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise InvalidInput("native import fingerprint must be SHA-256")


@dataclass(frozen=True, slots=True)
class NativeProject:
    id: UUID
    project_id: PlatformProjectId
    native_project_key: str
    version: int
    enabled: bool


@dataclass(frozen=True, slots=True)
class NativeImport:
    import_uuid: UUID
    operation_uuid: UUID
    project_id: PlatformProjectId
    native_project_id: UUID
    source_file_object_id: UUID
    source_file_version: int
    source_content_sha256: str
    source_size_bytes: int
    auto_analyze: bool
    native_artifact_id: str | None
    result_sha256: str | None
    state: str
    cleanup_state: str
    version: int


@dataclass(frozen=True, slots=True)
class GhidraObservation:
    import_uuid: UUID
    native_project_id: UUID
    source_file_object_id: UUID
    source_file_version: int
    native_artifact_id: str | None
    confirmed_at: datetime
    result_sha256: str | None = None
    # Set only after native Ghidra inventory confirms no artifact was created.
    confirmed_absent: bool = False


def _native_project(row: NativeProjectRow) -> NativeProject:
    return NativeProject(
        row.id,
        PlatformProjectId(row.project_id),
        row.native_project_key,
        row.version,
        row.enabled,
    )


def _native_import(row: NativeImportRow) -> NativeImport:
    return NativeImport(
        row.import_uuid,
        row.operation_uuid,
        PlatformProjectId(row.project_id),
        row.native_project_id,
        row.file_object_id,
        row.source_file_version,
        row.source_content_sha256,
        row.source_size_bytes,
        row.auto_analyze,
        row.native_artifact_id,
        row.result_sha256,
        row.status,
        row.cleanup_state,
        row.version,
    )


class NativeImportUnknown(Conflict):
    code = "native_import_unknown"


class TrustedNativeEvidenceVerifier(Protocol):
    """Pure local signature validation, never native network I/O in a DB UoW."""

    def verify_project(
        self,
        *,
        decision: ServiceAuthorizationDecision,
        native_project_key: str,
        evidence: object,
    ) -> bool:
        """Verify native project is owned by this Project and service."""
        ...

    def verify_import(
        self,
        *,
        decision: ServiceAuthorizationDecision,
        observation: GhidraObservation,
        evidence: object,
    ) -> bool:
        """Verify independent native inventory result/absence digest."""
        ...


class NativeImportLedger:
    def __init__(
        self,
        app: PlatformApplication,
        *,
        signing_key: bytes,
        validator: CurrentServiceDecisionValidator | None = None,
        native_verifier: TrustedNativeEvidenceVerifier | None = None,
    ) -> None:
        if len(signing_key) < 32:
            raise ValueError("native import HMAC key too short")
        self.app = app
        self.validator = validator
        self.native_verifier = native_verifier
        self._key = signing_key

    def _idempotency(self, key: str) -> str:
        if not 1 <= len(key) <= 128 or not key.isascii() or not key.isprintable():
            raise InvalidInput("native import requires bounded Idempotency-Key")
        return hmac.new(self._key, key.encode(), hashlib.sha256).hexdigest()

    async def _authorize(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        project_id: PlatformProjectId,
    ) -> None:
        if (
            decision.audience != "reverse"
            or decision.operation != "analysis.import"
            or decision.project_id != project_id
            or decision.expires_at <= _now()
        ):
            raise AccessDenied("verified Reverse/Project/AgentSession grant required")
        if self.validator is None:
            raise AccessDenied("C2 service identity validator is not configured")
        await self.validator.verify_live_decision(tx, decision)

    async def register_native_project(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        *,
        native_project_key: str,
        evidence: object,
    ) -> NativeProject:
        await self._authorize(tx, decision, decision.project_id)
        name = _opaque_name(native_project_key)
        if self.native_verifier is None or not self.native_verifier.verify_project(
            decision=decision,
            native_project_key=name,
            evidence=evidence,
        ):
            raise AccessDenied("C2 native Project ownership evidence is not verified")
        # The selected platform Project row already exists and is authorized;
        # locked to serialize ownership transfer against registration.
        project = await self.app.projects.get(tx, decision.project_id, lock=True)
        if project is None:
            raise AccessDenied("Project no longer available")
        row = cast(
            NativeProjectRow | None,
            await tx.scalar(
                select(NativeProjectRow)
                .where(
                    NativeProjectRow.project_id == decision.project_id,
                    NativeProjectRow.native_project_key == name,
                )
                .with_for_update()
            ),
        )
        if row is None:
            row = NativeProjectRow(
                id=uuid4(),
                project_id=decision.project_id,
                native_project_key=name,
                owner_service_id=decision.service_id,
                version=1,
                enabled=True,
            )
            tx.add(row)
            await tx.flush()
            self.app._audit(
                tx,
                actor=decision.actor_id,
                project=decision.project_id,
                action="reverse.native_project_registered",
                target=row.id,
                event={"native_project_revision": row.version},
            )
        elif row.owner_service_id != decision.service_id or not row.enabled:
            raise AccessDenied("native Ghidra project is not owned by this runtime")
        return _native_project(row)

    async def claim(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        *,
        native_project_id: UUID,
        file_object_id: UUID,
        expected_file_version: int,
        source_sha256: str,
        source_size_bytes: int,
        auto_analyze: bool,
        idempotency_key: str,
        operation_uuid: UUID,
        request_fingerprint: str,
        ttl_seconds: int = 1800,
    ) -> NativeImport:
        await self._authorize(tx, decision, decision.project_id)
        _digest(request_fingerprint)
        _digest(source_sha256)
        if not 0 <= source_size_bytes <= 100_000_000_000_000:
            raise InvalidInput("native staged source bytes exceed permitted limit")
        if type(auto_analyze) is not bool:
            raise InvalidInput("native auto_analyze must be explicit boolean")
        if not isinstance(operation_uuid, UUID) or operation_uuid.version != 4:
            raise InvalidInput("native import requires stable caller UUIDv4")
        if not 60 <= ttl_seconds <= 7200 or expected_file_version < 1:
            raise InvalidInput("native import TTL/source version outside limits")
        project = await self.app.projects.get(tx, decision.project_id, lock=True)
        if project is None:
            raise AccessDenied("Project no longer exists")
        native = await tx.scalar(
            select(NativeProjectRow)
            .where(
                NativeProjectRow.id == native_project_id,
                NativeProjectRow.project_id == decision.project_id,
            )
            .with_for_update()
        )
        if native is None or not native.enabled or native.owner_service_id != decision.service_id:
            raise AccessDenied("Ghidra project does not belong to runtime/Project")
        source = await tx.scalar(
            select(FileObjectRow)
            .where(
                FileObjectRow.id == file_object_id,
                FileObjectRow.project_id == decision.project_id,
            )
            .with_for_update()
        )
        if (
            source is None
            or source.deleted
            or source.version != expected_file_version
            or source.size_bytes != source_size_bytes
            or source.content_sha256 != source_sha256
        ):
            raise Conflict("confirmed Project File hash/size/version required for import")
        digest = self._idempotency(idempotency_key)
        previous = cast(
            NativeImportRow | None,
            await tx.scalar(
                select(NativeImportRow)
                .where(
                    NativeImportRow.project_id == decision.project_id,
                    NativeImportRow.idempotency_digest == digest,
                )
                .with_for_update()
            ),
        )
        if previous is not None:
            if (
                previous.request_fingerprint != request_fingerprint
                or previous.operation_uuid != operation_uuid
                or previous.actor_user_id != decision.actor_id
                or previous.native_project_id != native_project_id
                or previous.file_object_id != file_object_id
                or previous.source_file_version != expected_file_version
                or previous.source_content_sha256 != source_sha256
                or previous.source_size_bytes != source_size_bytes
                or previous.auto_analyze != auto_analyze
                or previous.agent_session_uuid != decision.session_uuid
                or previous.owner_service_id != decision.service_id
            ):
                raise Conflict("native import idempotency key reused")
            if previous.status in {"dispatched", "unknown"}:
                raise NativeImportUnknown("native import outcome requires reconciliation")
            return _native_import(previous)
        reused_uuid = await tx.scalar(
            select(NativeImportRow.import_uuid)
            .where(
                NativeImportRow.project_id == decision.project_id,
                NativeImportRow.operation_uuid == operation_uuid,
            )
            .limit(1)
        )
        if reused_uuid is not None:
            raise Conflict("Ghidra operation UUID reused under another idempotency key")
        # A different idempotency key cannot replay the same native effect
        # while a previous attempt may already have modified Ghidra.
        uncertain = await tx.scalar(
            select(NativeImportRow.import_uuid)
            .where(
                NativeImportRow.project_id == decision.project_id,
                NativeImportRow.native_project_id == native_project_id,
                NativeImportRow.file_object_id == file_object_id,
                NativeImportRow.source_file_version == expected_file_version,
                NativeImportRow.request_fingerprint == request_fingerprint,
                NativeImportRow.status.in_(("dispatched", "unknown")),
            )
            .limit(1)
        )
        if uncertain is not None:
            raise NativeImportUnknown("same native import effect is unconfirmed under another key")
        row = NativeImportRow(
            import_uuid=uuid4(),
            operation_uuid=operation_uuid,
            project_id=decision.project_id,
            native_project_id=native_project_id,
            file_object_id=file_object_id,
            source_file_version=expected_file_version,
            source_content_sha256=source_sha256,
            source_size_bytes=source_size_bytes,
            auto_analyze=auto_analyze,
            actor_user_id=decision.actor_id,
            agent_session_uuid=decision.session_uuid,
            owner_service_id=decision.service_id,
            idempotency_digest=digest,
            request_fingerprint=request_fingerprint,
            status="reserved",
            version=1,
            cleanup_state="not_requested",
            expires_at=_now() + timedelta(seconds=ttl_seconds),
        )
        tx.add(row)
        await tx.flush()
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="reverse.native_import_reserved",
            target=row.import_uuid,
            event={
                "native_project_id": str(native_project_id),
                "source_file_version": source.version,
            },
        )
        return _native_import(row)

    async def _owned(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        import_uuid: UUID,
        *,
        expected_version: int,
    ) -> NativeImportRow:
        await self._authorize(tx, decision, decision.project_id)
        row = cast(
            NativeImportRow | None,
            await tx.scalar(
                select(NativeImportRow)
                .where(
                    NativeImportRow.import_uuid == import_uuid,
                    NativeImportRow.project_id == decision.project_id,
                )
                .with_for_update()
            ),
        )
        if (
            row is None
            or row.agent_session_uuid != decision.session_uuid
            or row.actor_user_id != decision.actor_id
            or row.owner_service_id != decision.service_id
            or row.version != expected_version
        ):
            raise AccessDenied("native import ownership or revision mismatch")
        return row

    async def mark_dispatched(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        import_uuid: UUID,
        *,
        expected_version: int,
    ) -> NativeImport:
        await self._authorize(tx, decision, decision.project_id)
        project = await self.app.projects.get(tx, decision.project_id, lock=True)
        if project is None:
            raise AccessDenied("Project no longer exists")
        row = await self._owned(tx, decision, import_uuid, expected_version=expected_version)
        if row.status != "reserved" or row.expires_at <= _now():
            raise NativeImportUnknown("native import cannot be dispatched twice")
        native = await tx.scalar(
            select(NativeProjectRow)
            .where(
                NativeProjectRow.id == row.native_project_id,
                NativeProjectRow.project_id == decision.project_id,
            )
            .with_for_update()
        )
        if native is None or not native.enabled:
            raise AccessDenied("Ghidra target has been disabled")
        source = await tx.scalar(
            select(FileObjectRow)
            .where(
                FileObjectRow.id == row.file_object_id,
                FileObjectRow.project_id == decision.project_id,
            )
            .with_for_update()
        )
        if (
            source is None
            or source.deleted
            or source.version != row.source_file_version
            or source.content_sha256 != row.source_content_sha256
            or source.size_bytes != row.source_size_bytes
        ):
            raise NativeImportUnknown("verified source Files bytes changed before native dispatch")
        row.status = "dispatched"
        row.dispatched_at = _now()
        row.version += 1
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="reverse.native_import_dispatched",
            target=row.import_uuid,
            event={
                "native_import_version": row.version,
                "native_project_id": str(row.native_project_id),
            },
        )
        return _native_import(row)

    @staticmethod
    def _validate_observation(
        row: NativeImportRow,
        observation: GhidraObservation,
    ) -> None:
        if (
            observation.import_uuid != row.import_uuid
            or observation.native_project_id != row.native_project_id
            or observation.source_file_object_id != row.file_object_id
            or observation.source_file_version != row.source_file_version
            or observation.confirmed_at.tzinfo is None
            or observation.confirmed_at > _now() + timedelta(minutes=1)
            or bool(observation.native_artifact_id) == observation.confirmed_absent
        ):
            raise InvalidInput("Ghidra native observation does not match import")
        if observation.native_artifact_id is not None:
            _opaque_name(observation.native_artifact_id)
            if observation.result_sha256 is None:
                raise InvalidInput("Ghidra import requires independently attested result SHA-256")
            _digest(observation.result_sha256)
        elif observation.result_sha256 is not None:
            raise InvalidInput("Ghidra absent artifact cannot carry result digest")

    async def confirm(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        observation: GhidraObservation,
        *,
        expected_version: int,
        evidence: object,
    ) -> NativeImport:
        """Only cryptographically verified native inventory may settle import."""
        row = await self._owned(
            tx,
            decision,
            observation.import_uuid,
            expected_version=expected_version,
        )
        self._validate_observation(row, observation)
        if self.native_verifier is None or not self.native_verifier.verify_import(
            decision=decision,
            observation=observation,
            evidence=evidence,
        ):
            raise AccessDenied("C2 Ghidra native result proof is not verified")
        if row.status == "succeeded":
            if (
                row.native_artifact_id == observation.native_artifact_id
                and row.result_sha256 == observation.result_sha256
            ):
                return _native_import(row)
            raise Conflict("confirmed Ghidra artifact or result SHA differs")
        if row.status not in {"dispatched", "unknown"}:
            raise Conflict("native import must be dispatched or uncertain before confirmation")
        if observation.native_artifact_id is not None:
            row.status = "succeeded"
            row.native_artifact_id = observation.native_artifact_id
            row.result_sha256 = observation.result_sha256
        elif observation.confirmed_absent:
            row.status = "confirmed_absent"
            row.native_artifact_id = None
        row.resolved_at = observation.confirmed_at
        row.version += 1
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action=f"reverse.native_import_{row.status}",
            target=row.import_uuid,
            event={
                "native_project_id": str(row.native_project_id),
                "native_import_version": row.version,
                "artifact_confirmed": row.status == "succeeded",
            },
        )
        return _native_import(row)

    async def mark_unknown(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        import_uuid: UUID,
        *,
        expected_version: int,
    ) -> NativeImport:
        row = await self._owned(tx, decision, import_uuid, expected_version=expected_version)
        if row.status == "unknown":
            return _native_import(row)
        if row.status != "dispatched":
            raise Conflict("only dispatched imports can become unknown")
        row.status = "unknown"
        row.version += 1
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="reverse.native_import_unknown",
            target=row.import_uuid,
            event={"native_import_version": row.version, "reconciliation_required": True},
        )
        return _native_import(row)

    async def cancel_reserved(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        import_uuid: UUID,
        *,
        expected_version: int,
    ) -> NativeImport:
        row = await self._owned(tx, decision, import_uuid, expected_version=expected_version)
        if row.status != "reserved":
            raise NativeImportUnknown("cannot cancel a native import after dispatch")
        row.status = "cancelled"
        row.version += 1
        row.resolved_at = _now()
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="reverse.native_import_cancelled",
            target=row.import_uuid,
            event={"native_import_version": row.version},
        )
        return _native_import(row)

    async def request_source_cleanup(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        import_uuid: UUID,
        *,
        expected_version: int,
    ) -> NativeImport:
        """Outbox-only cleanup request; Files decides/acknowledges workspace bytes.

        Successful Ghidra artifacts are permanent; this operation NEVER
        emits a native Project/artifact deletion request.
        """
        row = await self._owned(tx, decision, import_uuid, expected_version=expected_version)
        if row.status not in {"succeeded", "confirmed_absent"}:
            raise NativeImportUnknown("Ghidra outcome not confirmed; cleanup forbidden")
        if row.cleanup_state == "requested":
            return _native_import(row)
        if row.cleanup_state != "not_requested":
            raise Conflict("native import cleanup was already resolved")
        row.cleanup_state = "requested"
        row.version += 1
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="reverse.source_cleanup_requested",
            target=row.import_uuid,
            event={
                "source_file_object_id": str(row.file_object_id),
                "source_file_version": row.source_file_version,
                "native_artifact_preserved": row.status == "succeeded",
            },
        )
        return _native_import(row)

    async def expire_batch(self, tx: AsyncSession, *, limit: int = 64) -> int:
        """Backend-only sweep; NEVER mark a timed-out native write failed."""
        if not 1 <= limit <= 256:
            raise InvalidInput("native import batch size outside allowed range")
        now = _now()
        rows = await tx.scalars(
            select(NativeImportRow)
            .where(
                NativeImportRow.status.in_(("reserved", "dispatched")),
                NativeImportRow.expires_at <= now,
            )
            .order_by(NativeImportRow.expires_at, NativeImportRow.import_uuid)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        count = 0
        for row in rows:
            row.status = "cancelled" if row.status == "reserved" else "unknown"
            if row.status == "cancelled":
                row.resolved_at = now
            row.version += 1
            self.app._audit(
                tx,
                actor=None,
                project=PlatformProjectId(row.project_id),
                action=f"reverse.native_import_{row.status}",
                target=row.import_uuid,
                event={
                    "native_import_version": row.version,
                    "reconciliation_required": row.status == "unknown",
                },
            )
            count += 1
        return count

    async def inspect_operation(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        operation_uuid: UUID,
    ) -> NativeImport | None:
        """Read-only Ghidra result lookup; unknown does not permit re-import."""
        await self._authorize(tx, decision, decision.project_id)
        if not isinstance(operation_uuid, UUID) or operation_uuid.version != 4:
            raise InvalidInput("Ghidra operation ID must be UUIDv4")
        row = await tx.scalar(
            select(NativeImportRow).where(
                NativeImportRow.project_id == decision.project_id,
                NativeImportRow.operation_uuid == operation_uuid,
                NativeImportRow.actor_user_id == decision.actor_id,
                NativeImportRow.agent_session_uuid == decision.session_uuid,
                NativeImportRow.owner_service_id == decision.service_id,
            )
        )
        return _native_import(row) if row is not None else None
