"""Exact accepted A5 Ghidra import-ledger client, private and unmounted.

Source: projects/_native_import_ledger.py. Native Project ID (UUID) differs
from native_project_key (opaque name) and PlatformProjectId. An import intent
requires a *committed* Project FileObject UUID/version, not just an uploaded
workspace path and SHA. No native import effect is executed by this module.
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

NativeState = Literal[
    "reserved", "dispatched", "unknown", "succeeded", "confirmed_absent", "cancelled"
]


class A5NativeLedgerError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class A5NativeProject:
    id: UUID
    project_id: UUID
    native_project_key: str
    version: int
    enabled: bool


@dataclass(frozen=True, slots=True)
class A5CommittedFile:
    """Project FileObjectRow identity; sha256 comes from separate Files snapshot."""

    file_object_id: UUID
    project_id: UUID
    file_version: int
    path_digest: str
    size_bytes: int
    inode_digest: str
    sha256: str


@dataclass(frozen=True, slots=True)
class A5NativeImport:
    import_uuid: UUID
    operation_uuid: UUID
    project_id: UUID
    native_project_id: UUID
    source_file_object_id: UUID
    source_file_version: int
    native_artifact_id: str | None
    state: NativeState
    cleanup_state: str
    version: int


@dataclass(frozen=True, slots=True)
class A5GhidraObservation:
    import_uuid: UUID
    native_project_id: UUID
    source_file_object_id: UUID
    source_file_version: int
    native_artifact_id: str | None
    confirmed_at: datetime
    confirmed_absent: bool = False


@dataclass(frozen=True, slots=True)
class A5NativeArtifactEvidence:
    """Verified Ghidra inventory result, not a caller-provided artifact name."""

    project_id: UUID
    agent_session_uuid: UUID
    actor_id: UUID
    native_project_id: UUID
    import_uuid: UUID
    source_file_object_id: UUID
    source_file_version: int
    native_artifact_id: str
    verified_at: datetime


class A5TrustedGhidraInventory(Protocol):
    """Backend/Ghidra owner validates inventory after irreversible import."""

    async def confirm_imported_artifact(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        native: A5NativeProject,
        source: A5CommittedFile,
        import_record: A5NativeImport,
    ) -> A5NativeArtifactEvidence: ...


class A5TrustedNativeImportPort(Protocol):
    """Backend SQL native-ledger adapter with sealed per-call A5 decision.

    Never accepts plain UUIDs, client-submitted `AuthorizedOperationReceipt`,
    or native JSON as trusted proof. Each UoW must verify current service,
    User/Project/AgentSession, native Project, committed Files object, CAS.
    """

    async def resolve_native_project(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        native_project_id: UUID,
    ) -> A5NativeProject: ...

    async def resolve_committed_file(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        path_digest: str,
        expected_sha256: str,
    ) -> A5CommittedFile: ...

    async def claim(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        native_project_id: UUID,
        file_object_id: UUID,
        expected_file_version: int,
        idempotency_key: str,
        operation_uuid: UUID,
        request_fingerprint: str,
        ttl_seconds: int,
    ) -> A5NativeImport: ...

    async def mark_dispatched(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        import_uuid: UUID,
        expected_version: int,
    ) -> A5NativeImport: ...

    async def mark_unknown(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        import_uuid: UUID,
        expected_version: int,
    ) -> A5NativeImport: ...

    async def confirm(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        observation: A5GhidraObservation,
        expected_version: int,
    ) -> A5NativeImport: ...

    async def inspect_operation(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        operation_uuid: UUID,
    ) -> A5NativeImport | None: ...


class A5NativeImportClient:
    """A5 native import intent/result ledger, NOT the Ghidra worker."""

    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        port: A5TrustedNativeImportPort | None = None,
        *,
        inventory: A5TrustedGhidraInventory | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise ValueError("A5 native import timeout invalid")
        self.authority = authority
        self.port = port
        self.inventory = inventory
        self.timeout_seconds = timeout_seconds

    async def _permit(self, invocation: ProjectInvocation) -> ProjectPermit:
        return await self.authority.require(invocation, "reverse.import")

    @staticmethod
    def _record(
        record: A5NativeImport,
        permit: ProjectPermit,
        native_project: A5NativeProject,
        file: A5CommittedFile,
        operation_uuid: UUID,
        *,
        status: NativeState,
        previous: A5NativeImport | None = None,
    ) -> A5NativeImport:
        if (
            not isinstance(record, A5NativeImport)
            or not isinstance(record.import_uuid, UUID)
            or record.import_uuid.version != 4
            or record.operation_uuid != operation_uuid
            or record.project_id != permit.project_id
            or record.native_project_id != native_project.id
            or record.source_file_object_id != file.file_object_id
            or record.source_file_version != file.file_version
            or record.state != status
            or type(record.version) is not int
            or record.version < 1
            or (
                previous is not None
                and (
                    record.import_uuid != previous.import_uuid
                    or record.version != previous.version + 1
                )
            )
        ):
            raise A5NativeLedgerError("A5_NATIVE_LEDGER_RECORD_INVALID")
        return record

    @staticmethod
    def expected_request_fingerprint(
        *,
        project_id: UUID,
        agent_session_uuid: UUID,
        native_project_id: UUID,
        source: A5CommittedFile,
        operation_uuid: UUID,
    ) -> str:
        """Bound SQL native intent to one immutable Project Files artifact."""
        raw = json.dumps(
            [
                "native-import-intent-v1",
                str(project_id),
                str(agent_session_uuid),
                str(native_project_id),
                str(source.file_object_id),
                source.file_version,
                source.path_digest,
                source.sha256,
                source.size_bytes,
                str(operation_uuid),
            ],
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        return hashlib.sha256(raw).hexdigest()

    async def claim_intent(
        self,
        invocation: ProjectInvocation,
        *,
        native_project_id: UUID,
        source: A5CommittedFile,
        operation_uuid: UUID,
        request_fingerprint: str,
    ) -> tuple[A5NativeProject, A5NativeImport]:
        """Claim only after A5 Files DB commit/version is source-confirmed."""
        if self.port is None:
            raise A5NativeLedgerError("A5_NATIVE_BACKEND_UNAVAILABLE")
        if (
            not isinstance(operation_uuid, UUID)
            or operation_uuid.version != 4
            or not isinstance(native_project_id, UUID)
            or not isinstance(request_fingerprint, str)
            or len(request_fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in request_fingerprint)
            or not isinstance(source, A5CommittedFile)
            or source.project_id != invocation.project_id
            or not isinstance(source.file_object_id, UUID)
            or type(source.file_version) is not int
            or source.file_version < 1
        ):
            raise A5NativeLedgerError("A5_NATIVE_REQUEST_INVALID")
        if request_fingerprint != self.expected_request_fingerprint(
            project_id=invocation.project_id,
            agent_session_uuid=invocation.session_uuid,
            native_project_id=native_project_id,
            source=source,
            operation_uuid=operation_uuid,
        ):
            raise A5NativeLedgerError("A5_NATIVE_REQUEST_FINGERPRINT_MISMATCH")
        permit = await self._permit(invocation)
        # An arbitrary caller-constructed file identity is not proof of a
        # committed FileObject. Backend must check FileQuotaLedger commit,
        # current Project owner and pinned snapshot bytes/inode before claim.
        if (
            len(source.path_digest) != 64
            or any(c not in "0123456789abcdef" for c in source.path_digest)
            or len(source.sha256) != 64
            or any(c not in "0123456789abcdef" for c in source.sha256)
            or len(source.inode_digest) != 64
            or any(c not in "0123456789abcdef" for c in source.inode_digest)
            or type(source.size_bytes) is not int
            or source.size_bytes < 0
        ):
            raise A5NativeLedgerError("A5_NATIVE_SOURCE_IDENTITY_INVALID")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                confirmed_source = await self.port.resolve_committed_file(
                    invocation,
                    permit=permit,
                    path_digest=source.path_digest,
                    expected_sha256=source.sha256,
                )
        except Exception as exc:
            raise A5NativeLedgerError("A5_NATIVE_SOURCE_UNAVAILABLE") from exc
        if not isinstance(confirmed_source, A5CommittedFile) or confirmed_source != source:
            raise A5NativeLedgerError("A5_NATIVE_SOURCE_STALE")
        # Files resolution may have taken time while Session/User/Project
        # permissions changed; never claim native intent from stale grants.
        updated = await self._permit(invocation)
        if (
            updated.actor_id != permit.actor_id
            or updated.session_uuid != permit.session_uuid
            or updated.decision_version != permit.decision_version
            or updated.project_access_revision != permit.project_access_revision
            or updated.project_owner_scope != permit.project_owner_scope
            or updated.project_owner_id != permit.project_owner_id
        ):
            raise A5NativeLedgerError("A5_NATIVE_PROJECT_ACCESS_STALE")
        permit = updated
        try:
            async with asyncio.timeout(self.timeout_seconds):
                native = await self.port.resolve_native_project(
                    invocation, permit=permit, native_project_id=native_project_id
                )
        except Exception as exc:
            raise A5NativeLedgerError("A5_NATIVE_PROJECT_UNAVAILABLE") from exc
        if (
            not isinstance(native, A5NativeProject)
            or native.id != native_project_id
            or native.project_id != permit.project_id
            or native.enabled is not True
            or type(native.version) is not int
            or native.version < 1
        ):
            raise A5NativeLedgerError("A5_NATIVE_PROJECT_INVALID")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                claimed = await self.port.claim(
                    invocation,
                    permit=permit,
                    native_project_id=native_project_id,
                    file_object_id=source.file_object_id,
                    expected_file_version=source.file_version,
                    idempotency_key=str(operation_uuid),
                    operation_uuid=operation_uuid,
                    request_fingerprint=request_fingerprint,
                    ttl_seconds=1800,
                )
        except Exception as exc:
            # A SQL claim could have committed before a lost response.
            raise A5NativeLedgerError("A5_NATIVE_CLAIM_OUTCOME_UNKNOWN") from exc
        self._record(claimed, permit, native, source, operation_uuid, status="reserved")
        return native, claimed

    async def inspect(
        self, invocation: ProjectInvocation, *, operation_uuid: UUID
    ) -> A5NativeImport | None:
        if self.port is None or not isinstance(operation_uuid, UUID) or operation_uuid.version != 4:
            raise A5NativeLedgerError("A5_NATIVE_INSPECT_UNAVAILABLE")
        permit = await self._permit(invocation)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.port.inspect_operation(
                    invocation, permit=permit, operation_uuid=operation_uuid
                )
        except Exception as exc:
            raise A5NativeLedgerError("A5_NATIVE_INSPECT_UNAVAILABLE") from exc
        if result is not None and (
            not isinstance(result, A5NativeImport)
            or result.operation_uuid != operation_uuid
            or result.project_id != permit.project_id
            or result.state
            not in {
                "reserved",
                "dispatched",
                "unknown",
                "succeeded",
                "confirmed_absent",
                "cancelled",
            }
        ):
            raise A5NativeLedgerError("A5_NATIVE_INSPECT_INVALID")
        return result

    async def dispatch(
        self,
        invocation: ProjectInvocation,
        *,
        native: A5NativeProject,
        source: A5CommittedFile,
        reserved: A5NativeImport,
    ) -> A5NativeImport:
        if self.port is None:
            raise A5NativeLedgerError("A5_NATIVE_BACKEND_UNAVAILABLE")
        permit = await self._permit(invocation)
        self._record(reserved, permit, native, source, reserved.operation_uuid, status="reserved")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.port.mark_dispatched(
                    invocation,
                    permit=permit,
                    import_uuid=reserved.import_uuid,
                    expected_version=reserved.version,
                )
        except Exception as exc:
            raise A5NativeLedgerError("A5_NATIVE_DISPATCH_OUTCOME_UNKNOWN") from exc
        return self._record(
            result,
            permit,
            native,
            source,
            reserved.operation_uuid,
            status="dispatched",
            previous=reserved,
        )

    async def confirm(
        self,
        invocation: ProjectInvocation,
        *,
        native: A5NativeProject,
        source: A5CommittedFile,
        dispatched: A5NativeImport,
    ) -> A5NativeImport:
        if self.port is None or self.inventory is None:
            raise A5NativeLedgerError("A5_NATIVE_INVENTORY_UNAVAILABLE")
        permit = await self._permit(invocation)
        self._record(
            dispatched, permit, native, source, dispatched.operation_uuid, status="dispatched"
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                evidence = await self.inventory.confirm_imported_artifact(
                    invocation,
                    permit=permit,
                    native=native,
                    source=source,
                    import_record=dispatched,
                )
        except Exception as exc:
            raise A5NativeLedgerError("A5_NATIVE_INVENTORY_OUTCOME_UNKNOWN") from exc
        if (
            not isinstance(evidence, A5NativeArtifactEvidence)
            or evidence.project_id != permit.project_id
            or evidence.agent_session_uuid != permit.session_uuid
            or evidence.actor_id != permit.actor_id
            or evidence.native_project_id != native.id
            or evidence.import_uuid != dispatched.import_uuid
            or evidence.source_file_object_id != source.file_object_id
            or evidence.source_file_version != source.file_version
            or not isinstance(evidence.native_artifact_id, str)
            or not 1 <= len(evidence.native_artifact_id) <= 256
            or any(
                not (ch.isascii() and (ch.isalnum() or ch in "._:-"))
                for ch in evidence.native_artifact_id
            )
            or not isinstance(evidence.verified_at, datetime)
            or evidence.verified_at.tzinfo is None
            or not datetime.now(UTC) - timedelta(seconds=60)
            <= evidence.verified_at
            <= datetime.now(UTC)
        ):
            raise A5NativeLedgerError("A5_NATIVE_INVENTORY_INVALID")
        observation = A5GhidraObservation(
            import_uuid=dispatched.import_uuid,
            native_project_id=native.id,
            source_file_object_id=source.file_object_id,
            source_file_version=source.file_version,
            native_artifact_id=evidence.native_artifact_id,
            confirmed_at=evidence.verified_at,
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.port.confirm(
                    invocation,
                    permit=permit,
                    observation=observation,
                    expected_version=dispatched.version,
                )
        except Exception as exc:
            raise A5NativeLedgerError("A5_NATIVE_CONFIRM_OUTCOME_UNKNOWN") from exc
        return self._record(
            result,
            permit,
            native,
            source,
            dispatched.operation_uuid,
            status="succeeded",
            previous=dispatched,
        )

    async def unknown(self, invocation: ProjectInvocation, *, dispatched: A5NativeImport) -> None:
        if self.port is None or dispatched.state != "dispatched":
            return
        try:
            permit = await self._permit(invocation)
            async with asyncio.timeout(self.timeout_seconds):
                await self.port.mark_unknown(
                    invocation,
                    permit=permit,
                    import_uuid=dispatched.import_uuid,
                    expected_version=dispatched.version,
                )
        except Exception:
            # Native importer may have committed after losing its result.
            # Never retry/import/delete; owner A5 expire_batch marks UNKNOWN.
            pass
