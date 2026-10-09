"""Durable, Project-scoped Files byte accounting for private streaming.

The Files worker performs actual filesystem operations. Backend reserves
project bytes BEFORE a stream, marks dispatch BEFORE I/O and records a trusted
observation AFTER I/O. Uncertain writes remain frozen until reconciled.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
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
from identity._domain import UserRole

from ._file_quota_persistence import (
    FileObjectRow,
    FileQuotaAccountRow,
    FileQuotaReservationRow,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _sha(value: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value, flags=re.ASCII):
        raise InvalidInput("file identity/operation fingerprint must be SHA-256")


@dataclass(frozen=True, slots=True)
class QuotaSummary:
    project_id: PlatformProjectId
    byte_limit: int
    used_bytes: int
    reserved_bytes: int
    frozen: bool
    revision: int


@dataclass(frozen=True, slots=True)
class QuotaReservation:
    reservation_id: UUID
    operation_uuid: UUID
    project_id: PlatformProjectId
    path_digest: str
    expected_content_sha256: str
    project_access_revision: str
    expected_file_version: int
    planned_bytes: int
    reserved_delta: int
    state: str
    revision: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class FilesObservation:
    """Authoritative post-write observation from a VERIFIED Files service.

    Not an upload request DTO. The producer must separately prove its own
    service identity and OS-root provenance under C2 before this can be used
    across processes.
    """

    reservation_id: UUID
    path_digest: str
    observed_file_version: int
    observed_size_bytes: int
    observed_inode_digest: str | None
    confirmed_at: datetime
    confirmed_absent: bool = False
    observed_content_sha256: str | None = None


class QuotaExceeded(Conflict):
    code = "quota_exceeded"


class FileOperationUnknown(Conflict):
    code = "file_operation_unknown"


def _summary(row: FileQuotaAccountRow) -> QuotaSummary:
    return QuotaSummary(
        PlatformProjectId(row.project_id),
        row.byte_limit,
        row.used_bytes,
        row.reserved_bytes,
        row.frozen,
        row.version,
    )


def _view(row: FileQuotaReservationRow) -> QuotaReservation:
    return QuotaReservation(
        reservation_id=row.reservation_id,
        operation_uuid=row.operation_uuid,
        project_id=PlatformProjectId(row.project_id),
        path_digest=row.path_digest,
        expected_content_sha256=row.expected_content_sha256,
        project_access_revision=row.project_access_revision,
        expected_file_version=row.expected_file_version,
        planned_bytes=row.planned_bytes,
        reserved_delta=row.reserved_delta,
        state=row.status,
        revision=row.version,
        expires_at=row.expires_at,
    )


class FileQuotaLedger:
    def __init__(
        self,
        app: PlatformApplication,
        *,
        signing_key: bytes,
        validator: CurrentServiceDecisionValidator | None = None,
    ) -> None:
        if len(signing_key) < 32:
            raise ValueError("file quota HMAC key too short")
        self.app = app
        self.validator = validator
        self._key = signing_key

    def _idempotency(self, value: str) -> str:
        if not 1 <= len(value) <= 128 or not value.isascii() or not value.isprintable():
            raise InvalidInput("Files write requires bounded Idempotency-Key")
        return hmac.new(self._key, value.encode(), hashlib.sha256).hexdigest()

    async def _authorize(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        project_id: PlatformProjectId,
    ) -> None:
        if (
            decision.audience != "files"
            or decision.operation != "files.write"
            or decision.project_id != project_id
            or decision.expires_at <= _now()
        ):
            raise AccessDenied("current Project Files service grant required")
        if self.validator is None:
            raise AccessDenied("C2 service identity validator is not configured")
        await self.validator.verify_live_decision(tx, decision)

    @staticmethod
    async def _account(
        tx: AsyncSession,
        project_id: PlatformProjectId,
    ) -> FileQuotaAccountRow:
        account = cast(
            FileQuotaAccountRow | None,
            await tx.scalar(
                select(FileQuotaAccountRow)
                .where(FileQuotaAccountRow.project_id == project_id)
                .with_for_update()
            ),
        )
        if account is None:
            raise AccessDenied("Project Files quota is not provisioned")
        return account

    async def provision(
        self,
        tx: AsyncSession,
        actor: object,
        *,
        project_id: PlatformProjectId,
        byte_limit: int,
        expected_version: int | None = None,
    ) -> QuotaSummary:
        """Only an in-process verified superuser can create/change a quota."""
        from authorization._project_access import CallerPrincipal

        if not isinstance(actor, CallerPrincipal):
            raise AccessDenied("verified operator required")
        user = await self.app.current_user(tx, actor, lock=True)
        if user.role is not UserRole.SUPERUSER:
            raise AccessDenied("superuser required for storage quota policy")
        if not 0 <= byte_limit <= 100_000_000_000_000:
            raise InvalidInput("byte limit exceeds allowed maximum")
        project = await self.app.projects.get(tx, project_id, lock=True)
        if project is None:
            raise AccessDenied("Project does not exist")
        current = await tx.scalar(
            select(FileQuotaAccountRow)
            .where(FileQuotaAccountRow.project_id == project_id)
            .with_for_update()
        )
        if current is None:
            if expected_version is not None:
                raise Conflict("quota account does not have an existing version")
            current = FileQuotaAccountRow(
                project_id=project_id,
                byte_limit=byte_limit,
                used_bytes=0,
                reserved_bytes=0,
                frozen=False,
                version=1,
            )
            tx.add(current)
        else:
            if expected_version is None or current.version != expected_version:
                raise Conflict("Project quota revision mismatch")
            current.byte_limit = byte_limit
            current.frozen = (
                current.frozen or current.used_bytes + current.reserved_bytes > byte_limit
            )
            current.version += 1
            current.updated_at = _now()
        await tx.flush()
        self.app._audit(
            tx,
            actor=actor.user_id,
            project=project_id,
            action="files.quota_configured",
            target=project_id,
            event={"quota_version": current.version, "byte_limit": byte_limit},
        )
        return _summary(current)

    async def summary(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
    ) -> QuotaSummary:
        await self._authorize(tx, decision, decision.project_id)
        account = await self._account(tx, decision.project_id)
        return _summary(account)

    async def reserve(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        *,
        path_digest: str,
        planned_bytes: int,
        expected_file_version: int,
        request_fingerprint: str,
        expected_content_sha256: str,
        project_access_revision: str,
        idempotency_key: str,
        operation_uuid: UUID,
        ttl_seconds: int = 600,
    ) -> QuotaReservation:
        await self._authorize(tx, decision, decision.project_id)
        _sha(path_digest)
        _sha(request_fingerprint)
        _sha(expected_content_sha256)
        _sha(project_access_revision)
        if project_access_revision != decision.decision_version:
            raise AccessDenied("Project permission revision changed before Files reserve")
        if not isinstance(operation_uuid, UUID) or operation_uuid.version != 4:
            raise InvalidInput("Files write requires stable caller UUIDv4")
        if (
            not 0 <= planned_bytes <= 100_000_000_000_000
            or expected_file_version < 0
            or not 30 <= ttl_seconds <= 3600
        ):
            raise InvalidInput("Files reservation size/version/TTL outside bounds")
        digest = self._idempotency(idempotency_key)
        account = await self._account(tx, decision.project_id)
        prior = cast(
            FileQuotaReservationRow | None,
            await tx.scalar(
                select(FileQuotaReservationRow)
                .where(
                    FileQuotaReservationRow.project_id == decision.project_id,
                    FileQuotaReservationRow.idempotency_digest == digest,
                )
                .with_for_update()
            ),
        )
        if prior is not None:
            if (
                prior.path_digest != path_digest
                or prior.request_fingerprint != request_fingerprint
                or prior.expected_content_sha256 != expected_content_sha256
                or prior.project_access_revision != project_access_revision
                or prior.operation_uuid != operation_uuid
                or prior.planned_bytes != planned_bytes
                or prior.expected_file_version != expected_file_version
                or prior.actor_user_id != decision.actor_id
                or prior.agent_session_uuid != decision.session_uuid
                or prior.owner_service_id != decision.service_id
            ):
                raise Conflict("Files idempotency key reused with different request")
            if prior.status in {"dispatched", "unknown"}:
                raise FileOperationUnknown("Files write was dispatched; reconcile outcome")
            return _view(prior)
        operation_reuse = await tx.scalar(
            select(FileQuotaReservationRow.reservation_id)
            .where(
                FileQuotaReservationRow.project_id == decision.project_id,
                FileQuotaReservationRow.operation_uuid == operation_uuid,
            )
            .limit(1)
        )
        if operation_reuse is not None:
            raise Conflict("Files operation UUID reused with another idempotency key")
        if account.frozen:
            raise FileOperationUnknown("Project Files quota requires reconciliation")
        pending = await tx.scalar(
            select(FileQuotaReservationRow.reservation_id)
            .where(
                FileQuotaReservationRow.project_id == decision.project_id,
                FileQuotaReservationRow.path_digest == path_digest,
                FileQuotaReservationRow.status.in_(("reserved", "dispatched", "unknown")),
            )
            .limit(1)
        )
        if pending is not None:
            raise Conflict("Files path has an unconfirmed write")
        file = cast(
            FileObjectRow | None,
            await tx.scalar(
                select(FileObjectRow)
                .where(
                    FileObjectRow.project_id == decision.project_id,
                    FileObjectRow.path_digest == path_digest,
                )
                .with_for_update()
            ),
        )
        actual_version = file.version if file else 0
        if actual_version != expected_file_version:
            raise Conflict("Files path revision mismatch")
        old_bytes = file.size_bytes if file and not file.deleted else 0
        needed = max(0, planned_bytes - old_bytes)
        if account.used_bytes + account.reserved_bytes + needed > account.byte_limit:
            raise QuotaExceeded("Project Files byte limit would be exceeded")
        now = _now()
        reservation = FileQuotaReservationRow(
            reservation_id=uuid4(),
            operation_uuid=operation_uuid,
            project_id=decision.project_id,
            agent_session_uuid=decision.session_uuid,
            actor_user_id=decision.actor_id,
            owner_service_id=decision.service_id,
            path_digest=path_digest,
            idempotency_digest=digest,
            request_fingerprint=request_fingerprint,
            expected_content_sha256=expected_content_sha256,
            project_access_revision=project_access_revision,
            expected_file_version=actual_version,
            prior_bytes=old_bytes,
            planned_bytes=planned_bytes,
            reserved_delta=needed,
            version=1,
            status="reserved",
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        tx.add(reservation)
        account.reserved_bytes += needed
        account.version += 1
        account.updated_at = now
        await tx.flush()
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="files.bytes_reserved",
            target=reservation.reservation_id,
            event={
                "quota_revision": account.version,
                "reservation_revision": reservation.version,
                "reserved_delta": needed,
            },
        )
        return _view(reservation)

    async def _reservation(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        reservation_id: UUID,
    ) -> tuple[FileQuotaAccountRow, FileQuotaReservationRow]:
        await self._authorize(tx, decision, decision.project_id)
        account = await self._account(tx, decision.project_id)
        record = cast(
            FileQuotaReservationRow | None,
            await tx.scalar(
                select(FileQuotaReservationRow)
                .where(
                    FileQuotaReservationRow.reservation_id == reservation_id,
                    FileQuotaReservationRow.project_id == decision.project_id,
                )
                .with_for_update()
            ),
        )
        if (
            record is None
            or record.agent_session_uuid != decision.session_uuid
            or record.owner_service_id != decision.service_id
            or record.actor_user_id != decision.actor_id
        ):
            raise AccessDenied("Files reservation is not owned by current operation")
        return account, record

    async def mark_dispatched(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        reservation_id: UUID,
        *,
        expected_version: int,
    ) -> QuotaReservation:
        account, row = await self._reservation(tx, decision, reservation_id)
        if row.version != expected_version or row.status != "reserved":
            raise FileOperationUnknown("Files write cannot be dispatched again")
        if row.expires_at <= _now():
            raise FileOperationUnknown("Files reservation expired before dispatch")
        row.status = "dispatched"
        row.dispatched_at = _now()
        row.version += 1
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="files.write_dispatched",
            target=row.reservation_id,
            event={"quota_revision": account.version, "reservation_revision": row.version},
        )
        return _view(row)

    @staticmethod
    def _observation(
        row: FileQuotaReservationRow,
        proof: FilesObservation,
        *,
        allow_unchanged: bool,
    ) -> bool:
        _sha(proof.path_digest)
        if proof.reservation_id != row.reservation_id or proof.path_digest != row.path_digest:
            raise InvalidInput("Files observation does not match reservation")
        if (
            proof.confirmed_at.tzinfo is None
            or proof.confirmed_at > _now() + timedelta(minutes=1)
            or proof.observed_size_bytes < 0
            or proof.observed_size_bytes > 100_000_000_000_000
        ):
            raise InvalidInput("Files confirmation timestamp/size is not valid")
        changed = proof.observed_file_version == row.expected_file_version + 1
        unchanged = proof.observed_file_version == row.expected_file_version
        if not changed and (not allow_unchanged or not unchanged):
            raise FileOperationUnknown("Files observation revision is not reconcilable")
        # Even an EMPTY file has an inode. A zero-byte file MUST NOT be
        # confused with proof that the path was removed.
        if changed:
            if proof.confirmed_absent or proof.observed_inode_digest is None:
                raise InvalidInput("committed Files object requires inode identity")
        elif proof.confirmed_absent:
            if proof.observed_size_bytes != 0 or proof.observed_inode_digest is not None:
                raise InvalidInput("confirmed-absent Files proof contradicts metadata")
        elif proof.observed_inode_digest is None:
            raise FileOperationUnknown("unchanged Files object requires inode proof")
        if proof.observed_inode_digest is not None:
            _sha(proof.observed_inode_digest)
        return changed

    async def _commit_observed(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        account: FileQuotaAccountRow,
        row: FileQuotaReservationRow,
        proof: FilesObservation,
    ) -> QuotaReservation:
        if row.status not in {"dispatched", "unknown"}:
            raise Conflict("Files write was not dispatched")
        self._observation(row, proof, allow_unchanged=False)
        if (
            proof.observed_content_sha256 is None
            or proof.observed_content_sha256 != row.expected_content_sha256
        ):
            raise FileOperationUnknown("Files content digest differs from signed write")
        file = cast(
            FileObjectRow | None,
            await tx.scalar(
                select(FileObjectRow)
                .where(
                    FileObjectRow.project_id == decision.project_id,
                    FileObjectRow.path_digest == row.path_digest,
                )
                .with_for_update()
            ),
        )
        if file is not None and file.version != row.expected_file_version:
            raise FileOperationUnknown("Files current metadata revision conflicts")
        if file is None and row.expected_file_version != 0:
            raise FileOperationUnknown("Files current metadata was removed")
        new_used = account.used_bytes + proof.observed_size_bytes - row.prior_bytes
        if new_used < 0:
            raise FileOperationUnknown("Files usage reconciliation underflow")
        if file is None:
            file = FileObjectRow(
                id=uuid4(),
                project_id=decision.project_id,
                path_digest=row.path_digest,
                inode_digest=proof.observed_inode_digest,
                content_sha256=proof.observed_content_sha256,
                size_bytes=proof.observed_size_bytes,
                version=proof.observed_file_version,
                deleted=False,
                confirmed_at=proof.confirmed_at,
            )
            tx.add(file)
        else:
            file.version = proof.observed_file_version
            file.inode_digest = proof.observed_inode_digest
            file.content_sha256 = proof.observed_content_sha256
            file.size_bytes = proof.observed_size_bytes
            file.deleted = False
            file.confirmed_at = proof.confirmed_at
        account.reserved_bytes -= row.reserved_delta
        account.used_bytes = new_used
        account.version += 1
        account.updated_at = _now()
        if account.used_bytes + account.reserved_bytes > account.byte_limit:
            account.frozen = True  # Record observed truth; deny further writes
        row.status = "committed"
        row.observed_size_bytes = proof.observed_size_bytes
        row.observed_file_version = proof.observed_file_version
        row.observed_inode_digest = proof.observed_inode_digest
        row.resolved_at = proof.confirmed_at
        row.version += 1
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="files.write_committed",
            target=row.reservation_id,
            event={
                "quota_revision": account.version,
                "reservation_revision": row.version,
                "file_version": file.version,
                "over_limit": account.frozen,
            },
        )
        return _view(row)

    async def finalize(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        proof: FilesObservation,
        *,
        expected_version: int,
    ) -> QuotaReservation:
        account, row = await self._reservation(tx, decision, proof.reservation_id)
        if row.status == "committed":
            if (
                not proof.confirmed_absent
                and row.observed_file_version == proof.observed_file_version
                and row.observed_size_bytes == proof.observed_size_bytes
                and row.observed_inode_digest == proof.observed_inode_digest
            ):
                return _view(row)
            raise Conflict("Files confirmed write replay differs")
        if row.version != expected_version:
            raise Conflict("Files reservation revision mismatch")
        result = await self._commit_observed(tx, decision, account, row, proof)
        await self._unfreeze_if_reconciled(tx, account)
        return result

    async def release(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        reservation_id: UUID,
        *,
        expected_version: int,
    ) -> QuotaReservation:
        """Release before dispatch only. Unknown disk writes cannot be freed."""
        account, row = await self._reservation(tx, decision, reservation_id)
        if row.status == "released":
            return _view(row)
        if row.version != expected_version:
            raise Conflict("Files reservation revision mismatch")
        if row.status != "reserved":
            raise FileOperationUnknown("dispatched Files write requires observation")
        account.reserved_bytes -= row.reserved_delta
        account.version += 1
        row.status = "released"
        row.version += 1
        row.resolved_at = _now()
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="files.reservation_released",
            target=reservation_id,
            event={"quota_revision": account.version, "reservation_revision": row.version},
        )
        return _view(row)

    async def mark_unknown(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        reservation_id: UUID,
        *,
        expected_version: int,
    ) -> QuotaReservation:
        account, row = await self._reservation(tx, decision, reservation_id)
        if row.status == "unknown":
            return _view(row)
        if row.version != expected_version or row.status != "dispatched":
            raise Conflict("Files reservation cannot become unknown")
        row.status = "unknown"
        row.version += 1
        account.frozen = True
        account.version += 1
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="files.write_outcome_unknown",
            target=reservation_id,
            event={"quota_revision": account.version, "reservation_revision": row.version},
        )
        return _view(row)

    @staticmethod
    async def _unfreeze_if_reconciled(
        tx: AsyncSession,
        account: FileQuotaAccountRow,
    ) -> None:
        await tx.flush()
        unconfirmed = await tx.scalar(
            select(FileQuotaReservationRow.reservation_id)
            .where(
                FileQuotaReservationRow.project_id == account.project_id,
                FileQuotaReservationRow.status == "unknown",
            )
            .limit(1)
        )
        if (
            unconfirmed is None
            and account.used_bytes + account.reserved_bytes <= account.byte_limit
        ):
            account.frozen = False

    async def reconcile(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        proof: FilesObservation,
        *,
        expected_version: int,
    ) -> QuotaReservation:
        account, row = await self._reservation(tx, decision, proof.reservation_id)
        if row.status != "unknown" or row.version != expected_version:
            raise Conflict("Files reconciliation requires current unknown reservation")
        changed = self._observation(row, proof, allow_unchanged=True)
        if changed:
            result = await self._commit_observed(tx, decision, account, row, proof)
        else:
            # Files worker proves previous inode/path/revision/size still
            # matches, or explicitly attests that a never-created path is
            # absent. No silent release on a guessed zero-byte file.
            current_file = await tx.scalar(
                select(FileObjectRow)
                .where(
                    FileObjectRow.project_id == decision.project_id,
                    FileObjectRow.path_digest == row.path_digest,
                )
                .with_for_update()
            )
            if current_file is None:
                if (
                    row.expected_file_version != 0
                    or not proof.confirmed_absent
                    or proof.observed_size_bytes != 0
                ):
                    raise FileOperationUnknown("missing Files object not proven absent")
            elif (
                proof.confirmed_absent
                or current_file.deleted
                or current_file.version != row.expected_file_version
                or current_file.size_bytes != proof.observed_size_bytes
                or current_file.inode_digest != proof.observed_inode_digest
                or (
                    current_file.content_sha256 is not None
                    and current_file.content_sha256 != proof.observed_content_sha256
                )
            ):
                raise FileOperationUnknown("Files inode/revision did not match prewrite state")
            if proof.observed_size_bytes != row.prior_bytes:
                raise FileOperationUnknown("unchanged file size differs from prior")
            account.reserved_bytes -= row.reserved_delta
            account.version += 1
            row.status = "released"
            row.resolved_at = proof.confirmed_at
            row.version += 1
            result = _view(row)
            self.app._audit(
                tx,
                actor=decision.actor_id,
                project=decision.project_id,
                action="files.write_reconciled_unmodified",
                target=row.reservation_id,
                event={"quota_revision": account.version},
            )
        await self._unfreeze_if_reconciled(tx, account)
        return result

    async def expire_reservations(
        self,
        tx: AsyncSession,
        *,
        limit: int = 64,
    ) -> int:
        """Backend-only sweep: RESERVED release; DISPATCHED becomes UNKNOWN."""
        if not 1 <= limit <= 256:
            raise InvalidInput("quota sweep batch limit outside allowed range")
        now = _now()
        ids = await tx.scalars(
            select(FileQuotaReservationRow.reservation_id)
            .where(
                FileQuotaReservationRow.status.in_(("reserved", "dispatched")),
                FileQuotaReservationRow.expires_at <= now,
            )
            .order_by(
                FileQuotaReservationRow.expires_at,
                FileQuotaReservationRow.reservation_id,
            )
            .limit(limit)
        )
        count = 0
        for reservation_id in ids:
            probe = await tx.scalar(
                select(FileQuotaReservationRow).where(
                    FileQuotaReservationRow.reservation_id == reservation_id
                )
            )
            if probe is None:
                continue
            account = await self._account(tx, PlatformProjectId(probe.project_id))
            row = await tx.scalar(
                select(FileQuotaReservationRow)
                .where(FileQuotaReservationRow.reservation_id == reservation_id)
                .with_for_update()
            )
            if row is None or row.status not in {"reserved", "dispatched"}:
                continue
            if row.status == "reserved":
                account.reserved_bytes -= row.reserved_delta
                row.status = "released"
            else:
                row.status = "unknown"
                account.frozen = True
            row.version += 1
            row.resolved_at = now if row.status == "released" else None
            account.version += 1
            self.app._audit(
                tx,
                actor=None,
                project=PlatformProjectId(row.project_id),
                action=f"files.reservation_{row.status}",
                target=row.reservation_id,
                event={"quota_revision": account.version, "reservation_revision": row.version},
            )
            count += 1
        return count

    async def inspect_operation(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        operation_uuid: UUID,
    ) -> QuotaReservation | None:
        """Read-only Files outcome lookup, never a fresh reserve or release."""
        await self._authorize(tx, decision, decision.project_id)
        if not isinstance(operation_uuid, UUID) or operation_uuid.version != 4:
            raise InvalidInput("Files operation ID must be UUIDv4")
        row = await tx.scalar(
            select(FileQuotaReservationRow).where(
                FileQuotaReservationRow.project_id == decision.project_id,
                FileQuotaReservationRow.operation_uuid == operation_uuid,
                FileQuotaReservationRow.actor_user_id == decision.actor_id,
                FileQuotaReservationRow.agent_session_uuid == decision.session_uuid,
                FileQuotaReservationRow.owner_service_id == decision.service_id,
            )
        )
        return _view(row) if row is not None else None
