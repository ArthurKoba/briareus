"""Backend A5 exact Files quota protocol and fail-closed private consumer.

Accepted source: projects/_file_quota.{QuotaReservation,FilesObservation,
FileQuotaLedger}. The Backend *owns* durable SQL and a HMAC-sealed verified
ServiceAuthorizationDecision, fresh live grant, owner and replay checks per
transaction. A serialized A5 reservation is NOT an authorization capability.
No accepted C1-B2 transport, ledger instance, or public Files endpoint exists.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from modules.project_runtime import ProjectInvocation, ProjectPermit, ProjectRuntimeAuthority
from modules.project_runtime.authorization import valid_project_revision

A5FileState = Literal["reserved", "dispatched", "committed", "released", "unknown"]


class A5FilesLedgerError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class A5QuotaReservation:
    """Exact accepted A5 SQL-ledger QuotaReservation public field projection."""

    reservation_id: UUID
    operation_uuid: UUID
    project_id: UUID
    path_digest: str
    expected_file_version: int
    planned_bytes: int
    reserved_delta: int
    state: A5FileState
    revision: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class A5FilesObservation:
    """Exact accepted A5 FilesObservation, produced only by Files worker."""

    reservation_id: UUID
    path_digest: str
    observed_file_version: int
    observed_size_bytes: int
    observed_inode_digest: str | None
    confirmed_at: datetime
    confirmed_absent: bool = False


class A5TrustedFileQuotaPort(Protocol):
    """Trusted Backend adapter: per-operation service+human proof required.

    Each implementation invokes accepted FileQuotaLedger inside a fresh
    authorized SQL UoW and checks the still-current A5 signed decision via
    ServiceIdentityAuthority.verify_live_decision. Never use HTTP JSON, a
    stale permit, or a client-supplied UUID as a grant.
    """

    async def reserve(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        path_digest: str,
        planned_bytes: int,
        expected_file_version: int,
        request_fingerprint: str,
        idempotency_key: str,
        operation_uuid: UUID,
        ttl_seconds: int,
    ) -> A5QuotaReservation: ...

    async def mark_dispatched(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        reservation_id: UUID,
        expected_version: int,
    ) -> A5QuotaReservation: ...

    async def finalize(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        observation: A5FilesObservation,
        expected_version: int,
    ) -> A5QuotaReservation: ...

    async def mark_unknown(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        reservation_id: UUID,
        expected_version: int,
    ) -> A5QuotaReservation: ...

    async def inspect_operation(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        operation_uuid: UUID,
    ) -> A5QuotaReservation | None: ...

    async def release(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        reservation_id: UUID,
        expected_version: int,
    ) -> A5QuotaReservation: ...

    async def reconcile(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        observation: A5FilesObservation,
        expected_version: int,
    ) -> A5QuotaReservation: ...


class A5TrustedFilesystemObserver(Protocol):
    """Trusted Project Files owner; NOT submitted HTTP/MCP observation.

    Must pin the Project root and file descriptor, verify source path, inode,
    mode, link count, Project+Files OS ownership, and independently confirm
    Backend Files row expected_file_version. An absent path is proven only by
    observing pinned parent directory with current Project ownership rights.
    """

    async def observe_outcome(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        reservation: A5QuotaReservation,
    ) -> A5FilesObservation: ...


class A5FileQuotaFlow:
    """Source-aligned private Files reservation/dispatch/confirm workflow."""

    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        source: A5TrustedFileQuotaPort | None = None,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise ValueError("A5 quota timeout invalid")
        self.authority = authority
        self.source = source
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _path_digest(destination: str) -> str:
        return hashlib.sha256(destination.encode("utf-8", errors="strict")).hexdigest()

    @staticmethod
    def _fingerprint(
        permit: ProjectPermit,
        destination: str,
        operation_uuid: UUID,
        expected_sha256: str,
        size: int,
    ) -> str:
        # Idempotency includes the exact canonical Project path and payload,
        # with Project/Session/actor and no plaintext file content in ledger.
        raw = json.dumps(
            [
                str(permit.project_id),
                str(permit.actor_id),
                str(permit.session_uuid),
                str(operation_uuid),
                destination,
                expected_sha256,
                size,
                0,
            ],
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def _permit(
        self, invocation: ProjectInvocation, previous: ProjectPermit
    ) -> ProjectPermit:
        current = await self.authority.require(invocation, "files.write")
        if (
            current.project_id != previous.project_id
            or current.actor_id != previous.actor_id
            or current.session_uuid != previous.session_uuid
            or current.project_access_revision != previous.project_access_revision
            or current.decision_version != previous.decision_version
            or current.project_owner_scope != previous.project_owner_scope
            or current.project_owner_id != previous.project_owner_id
        ):
            raise A5FilesLedgerError("A5_FILES_ACCESS_STALE")
        return current

    @staticmethod
    def _record(
        record: A5QuotaReservation,
        permit: ProjectPermit,
        operation_uuid: UUID,
        path_digest: str,
        planned_bytes: int,
        *,
        expected_status: A5FileState,
        expected_revision: int | None = None,
        previous: A5QuotaReservation | None = None,
    ) -> A5QuotaReservation:
        if (
            not isinstance(record, A5QuotaReservation)
            or not isinstance(record.reservation_id, UUID)
            or record.reservation_id.version != 4
            or record.operation_uuid != operation_uuid
            or record.project_id != permit.project_id
            or record.path_digest != path_digest
            or record.expected_file_version != 0  # create-only, no overwrite
            or record.planned_bytes != planned_bytes
            or record.reserved_delta != planned_bytes
            or record.state != expected_status
            or type(record.revision) is not int
            or record.revision < 1
            or (expected_revision is not None and record.revision != expected_revision)
            or not isinstance(record.expires_at, datetime)
            or record.expires_at.tzinfo is None
            or (
                previous is not None
                and (
                    record.reservation_id != previous.reservation_id
                    or record.operation_uuid != previous.operation_uuid
                    or record.project_id != previous.project_id
                    or record.path_digest != previous.path_digest
                    or record.expected_file_version != previous.expected_file_version
                    or record.planned_bytes != previous.planned_bytes
                    or record.reserved_delta != previous.reserved_delta
                    or record.expires_at != previous.expires_at
                )
            )
        ):
            raise A5FilesLedgerError("A5_FILES_RESERVATION_INVALID")
        return record

    async def reserve(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        destination: str,
        expected_size: int,
        expected_sha256: str,
        operation_uuid: UUID,
    ) -> A5QuotaReservation:
        if self.source is None:
            raise A5FilesLedgerError("A5_QUOTA_BACKEND_NOT_CONFIGURED")
        if (
            permit.action != "files.write"
            or not valid_project_revision(permit.project_access_revision)
            or not isinstance(operation_uuid, UUID)
            or operation_uuid.version != 4
            or type(expected_size) is not int
            or not 0 <= expected_size <= 100_000_000_000_000
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(c not in "0123456789abcdef" for c in expected_sha256)
        ):
            raise A5FilesLedgerError("A5_FILES_REQUEST_INVALID")
        path_digest = self._path_digest(destination)
        fresh = await self._permit(invocation, permit)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.source.reserve(
                    invocation,
                    permit=fresh,
                    path_digest=path_digest,
                    planned_bytes=expected_size,
                    expected_file_version=0,
                    request_fingerprint=self._fingerprint(
                        permit, destination, operation_uuid, expected_sha256, expected_size
                    ),
                    idempotency_key=str(operation_uuid),
                    operation_uuid=operation_uuid,
                    ttl_seconds=600,
                )
        except Exception as exc:
            # Backend could have committed a RESERVED row without response.
            # Reconcile the SAME operation key, never mint another UUID.
            raise A5FilesLedgerError("A5_FILES_RESERVE_OUTCOME_UNKNOWN") from exc
        self._record(
            result,
            permit,
            operation_uuid,
            path_digest,
            expected_size,
            expected_status="reserved",
            expected_revision=1,
        )
        if result.expires_at <= datetime.now(UTC):
            raise A5FilesLedgerError("A5_FILES_RESERVATION_EXPIRED")
        return result

    async def dispatch(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        reserved: A5QuotaReservation,
    ) -> A5QuotaReservation:
        if self.source is None:
            raise A5FilesLedgerError("A5_QUOTA_BACKEND_NOT_CONFIGURED")
        self._record(
            reserved,
            permit,
            reserved.operation_uuid,
            reserved.path_digest,
            reserved.planned_bytes,
            expected_status="reserved",
        )
        fresh = await self._permit(invocation, permit)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.source.mark_dispatched(
                    invocation,
                    permit=fresh,
                    reservation_id=reserved.reservation_id,
                    expected_version=reserved.revision,
                )
        except Exception as exc:
            raise A5FilesLedgerError("A5_FILES_DISPATCH_OUTCOME_UNKNOWN") from exc
        return self._record(
            result,
            permit,
            reserved.operation_uuid,
            reserved.path_digest,
            reserved.planned_bytes,
            expected_status="dispatched",
            expected_revision=reserved.revision + 1,
            previous=reserved,
        )

    async def finalize(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        dispatched: A5QuotaReservation,
        inode_digest: str,
        size: int,
    ) -> A5QuotaReservation:
        if self.source is None:
            raise A5FilesLedgerError("A5_QUOTA_BACKEND_NOT_CONFIGURED")
        if (
            dispatched.state != "dispatched"
            or size != dispatched.planned_bytes
            or len(inode_digest) != 64
            or any(c not in "0123456789abcdef" for c in inode_digest)
        ):
            raise A5FilesLedgerError("A5_FILES_COMMIT_EVIDENCE_INVALID")
        fresh = await self._permit(invocation, permit)
        observation = A5FilesObservation(
            reservation_id=dispatched.reservation_id,
            path_digest=dispatched.path_digest,
            observed_file_version=dispatched.expected_file_version + 1,
            observed_size_bytes=size,
            observed_inode_digest=inode_digest,
            confirmed_at=datetime.now(UTC),
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.source.finalize(
                    invocation,
                    permit=fresh,
                    observation=observation,
                    expected_version=dispatched.revision,
                )
        except Exception as exc:
            raise A5FilesLedgerError("A5_FILES_FINALIZE_OUTCOME_UNKNOWN") from exc
        return self._record(
            result,
            permit,
            dispatched.operation_uuid,
            dispatched.path_digest,
            dispatched.planned_bytes,
            expected_status="committed",
            expected_revision=dispatched.revision + 1,
            previous=dispatched,
        )

    async def unknown(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        dispatched: A5QuotaReservation,
    ) -> None:
        if self.source is None or dispatched.state != "dispatched":
            return
        try:
            fresh = await self._permit(invocation, permit)
            async with asyncio.timeout(self.timeout_seconds):
                await self.source.mark_unknown(
                    invocation,
                    permit=fresh,
                    reservation_id=dispatched.reservation_id,
                    expected_version=dispatched.revision,
                )
        except Exception:
            # A5 sweeper also moves stranded DISPATCHED rows to UNKNOWN.
            # A lost response must not trigger a new write or quota release.
            pass

    async def release_reserved(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        reserved: A5QuotaReservation,
    ) -> A5QuotaReservation:
        """Only before DISPATCH. NEVER release an unknown external write."""
        if self.source is None:
            raise A5FilesLedgerError("A5_QUOTA_BACKEND_NOT_CONFIGURED")
        if reserved.state != "reserved":
            raise A5FilesLedgerError("A5_FILES_RELEASE_AFTER_DISPATCH_DENIED")
        fresh = await self._permit(invocation, permit)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.source.release(
                    invocation,
                    permit=fresh,
                    reservation_id=reserved.reservation_id,
                    expected_version=reserved.revision,
                )
        except Exception as exc:
            raise A5FilesLedgerError("A5_FILES_RELEASE_OUTCOME_UNKNOWN") from exc
        return self._record(
            result,
            permit,
            reserved.operation_uuid,
            reserved.path_digest,
            reserved.planned_bytes,
            expected_status="released",
            expected_revision=reserved.revision + 1,
            previous=reserved,
        )

    async def reconcile_unknown(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        operation_uuid: UUID,
        observer: A5TrustedFilesystemObserver | None,
    ) -> A5QuotaReservation:
        """Use independent inode/SQL evidence; absence is not guesswork."""
        if self.source is None or observer is None:
            raise A5FilesLedgerError("A5_FILES_RECONCILIATION_UNAVAILABLE")
        current = await self.inspect(invocation, permit=permit, operation_uuid=operation_uuid)
        if current is None or current.state != "unknown":
            raise A5FilesLedgerError("A5_FILES_NOT_UNKNOWN")
        fresh = await self._permit(invocation, permit)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                proof = await observer.observe_outcome(
                    invocation, permit=fresh, reservation=current
                )
        except Exception as exc:
            raise A5FilesLedgerError("A5_FILES_OBSERVATION_UNAVAILABLE") from exc
        if (
            not isinstance(proof, A5FilesObservation)
            or proof.reservation_id != current.reservation_id
            or proof.path_digest != current.path_digest
            or proof.observed_file_version
            not in {
                current.expected_file_version,
                current.expected_file_version + 1,
            }
            or type(proof.observed_size_bytes) is not int
            or proof.observed_size_bytes < 0
            or not isinstance(proof.confirmed_at, datetime)
            or proof.confirmed_at.tzinfo is None
            or not datetime.now(UTC) - timedelta(seconds=30)
            <= proof.confirmed_at
            <= datetime.now(UTC)
            or (proof.confirmed_absent and proof.observed_inode_digest is not None)
            or (
                not proof.confirmed_absent
                and (
                    not isinstance(proof.observed_inode_digest, str)
                    or len(proof.observed_inode_digest) != 64
                    or any(c not in "0123456789abcdef" for c in proof.observed_inode_digest)
                )
            )
        ):
            raise A5FilesLedgerError("A5_FILES_OBSERVATION_INVALID")
        # Final decision occurs ONLY under Backend A5 FileQuotaLedger.reconcile
        # transactional locks and live HMAC service decision. It can freeze a
        # Project on uncertain effects, never infer non-effect from HTTP loss.
        fresh = await self._permit(invocation, permit)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.source.reconcile(
                    invocation,
                    permit=fresh,
                    observation=proof,
                    expected_version=current.revision,
                )
        except Exception as exc:
            raise A5FilesLedgerError("A5_FILES_RECONCILE_OUTCOME_UNKNOWN") from exc
        if (
            not isinstance(result, A5QuotaReservation)
            or result.project_id != permit.project_id
            or result.operation_uuid != operation_uuid
            or result.reservation_id != current.reservation_id
            or result.path_digest != current.path_digest
            or result.state not in {"committed", "released"}
            or result.revision != current.revision + 1
        ):
            raise A5FilesLedgerError("A5_FILES_RECONCILE_RESULT_INVALID")
        return self._record(
            result,
            permit,
            operation_uuid,
            current.path_digest,
            current.planned_bytes,
            expected_status=result.state,
            expected_revision=current.revision + 1,
            previous=current,
        )

    async def inspect(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        operation_uuid: UUID,
    ) -> A5QuotaReservation | None:
        if self.source is None:
            raise A5FilesLedgerError("A5_QUOTA_BACKEND_NOT_CONFIGURED")
        fresh = await self._permit(invocation, permit)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.source.inspect_operation(
                    invocation,
                    permit=fresh,
                    operation_uuid=operation_uuid,
                )
        except Exception as exc:
            raise A5FilesLedgerError("A5_FILES_INSPECTION_UNAVAILABLE") from exc
        if result is not None and (
            not isinstance(result, A5QuotaReservation)
            or not isinstance(result.reservation_id, UUID)
            or result.reservation_id.version != 4
            or result.project_id != permit.project_id
            or result.operation_uuid != operation_uuid
            or not valid_project_revision(result.path_digest)
            or type(result.expected_file_version) is not int
            or result.expected_file_version != 0
            or type(result.planned_bytes) is not int
            or not 0 <= result.planned_bytes <= 100_000_000_000_000
            or result.reserved_delta != result.planned_bytes
            or result.state not in {"reserved", "dispatched", "committed", "released", "unknown"}
            or type(result.revision) is not int
            or result.revision < 1
            or not isinstance(result.expires_at, datetime)
            or result.expires_at.tzinfo is None
        ):
            raise A5FilesLedgerError("A5_FILES_INSPECTION_INVALID")
        return result
