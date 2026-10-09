"""Private Platform Project → native Ghidra artifact transfer.

Do not mount this transport before C1-B confirms Project/Ghidra ownership,
service identity and durable idempotency. Imported Reverse artifacts belong to
Ghidra, and deleting Files workspace content never deletes imported artifacts.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Protocol
from uuid import UUID

from common.models import JsonObject
from modules.files.project_files import ProjectFilesService
from modules.project_runtime import ProjectInvocation, ProjectPermit, ProjectRuntimeAuthority
from modules.project_runtime.authorization import valid_project_revision

from .import_ledger import (
    NativeImportClaim,
    NativeImportIdentity,
    NativeImportLedgerPort,
    NativeImportReconciliation,
)

BackendCall = Callable[[str, JsonObject], Awaitable[JsonObject]]


@dataclass(frozen=True, slots=True)
class GhidraProjectAssociation:
    platform_project_id: UUID
    native_ghidra_project_id: str


@dataclass(frozen=True, slots=True)
class ProjectReverseAssociationView:
    """Only independently verified native association, not a guessed Ghidra API."""

    platform_project_id: UUID
    native_ghidra_project_id: str
    storage_owner: str = "ghidra"
    native_health_verified: bool = False


@dataclass(frozen=True, slots=True)
class ProjectReverseOperationView:
    platform_project_id: UUID
    native_ghidra_project_id: str
    operation_uuid: UUID
    state: str
    source_sha256: str
    source_bytes: int
    native_evidence_verified: bool
    result_sha256: str | None


@dataclass(frozen=True, slots=True)
class NativeStagingAttestation:
    """Trusted native-side stage provenance, NEVER arbitrary HTTP response."""

    platform_project_id: UUID
    agent_session_uuid: UUID
    actor_id: UUID
    project_access_revision: str
    native_project_id: str
    stage_id: str
    native_stage_path: str
    source_sha256: str
    size_bytes: int
    expires_at: datetime


class NativeStageVerifier(Protocol):
    """Backend/Ghidra-owned validation of stage path inside native storage."""

    async def verify_native_stage(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        native_project_id: str,
        stage_id: str,
        native_path: str,
        source_sha256: str,
        size_bytes: int,
    ) -> NativeStagingAttestation: ...


class GhidraProjectPort(Protocol):
    async def resolve_owned_project(
        self, invocation: ProjectInvocation, native_project_id: str
    ) -> GhidraProjectAssociation: ...


class ProjectReverseTransferError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProjectReverseImportResult:
    platform_project_id: UUID
    native_ghidra_project_id: str
    source_path: str
    source_sha256: str
    size_bytes: int
    response: JsonObject
    staging_cleanup_failed: bool


class ProjectReverseTransfer:
    """Bounded staging with verified native-ID association and best-effort cleanup.

    The existing Analysis MCP publishes different tools; this private adapter
    will not become callable until the orchestrator approves Backend C1-B/C2.
    """

    def __init__(
        self,
        *,
        authority: ProjectRuntimeAuthority,
        files: ProjectFilesService,
        native_projects: GhidraProjectPort | None = None,
        backend_call: BackendCall | None = None,
        chunk_bytes: int = 1024 * 1024,
        ledger: NativeImportLedgerPort | None = None,
        stage_verifier: NativeStageVerifier | None = None,
        backend_timeout_seconds: float = 60.0,
    ) -> None:
        if not 0 < chunk_bytes <= files.max_file_bytes:
            raise ValueError("chunk_bytes must fit within the project file limit")
        if not math.isfinite(backend_timeout_seconds) or not 0 < backend_timeout_seconds <= 300:
            raise ValueError("Reverse backend timeout must be finite and positive")
        self.backend_timeout_seconds = backend_timeout_seconds
        self.authority = authority
        self.files = files
        self.native_projects = native_projects
        self.backend_call = backend_call
        self.ledger = ledger
        self.stage_verifier = stage_verifier
        self.chunk_bytes = chunk_bytes

    async def _call(self, name: str, arguments: JsonObject) -> JsonObject:
        if self.backend_call is None:
            raise ProjectReverseTransferError("REVERSE_BACKEND_UNAVAILABLE")
        # Both staging calls and native import must have a bounded deadline.
        # A timeout during import is an UNKNOWN outcome, never a retry signal.
        async with asyncio.timeout(self.backend_timeout_seconds):
            result = await self.backend_call(name, arguments)
        if not isinstance(result, dict) or result.get("success") is False:
            raise ProjectReverseTransferError("REVERSE_BACKEND_FAILED")
        error = result.get("error")
        if isinstance(error, str) and error:
            raise ProjectReverseTransferError("REVERSE_BACKEND_FAILED")
        return result

    async def association_metadata(
        self,
        invocation: ProjectInvocation,
        *,
        native_project_id: str,
    ) -> ProjectReverseAssociationView:
        """Source-side read projection, unavailable until Reverse READ grant.

        An existing native `GhidraProjectPort` confirms ownership; this does
        NOT invent a native REST status endpoint, run Ghidra or assert health.
        """
        await self.authority.require(invocation, "reverse.read")
        if self.native_projects is None:
            raise ProjectReverseTransferError("REVERSE_PROJECT_PORT_UNAVAILABLE")
        if not native_project_id or len(native_project_id) > 256:
            raise ProjectReverseTransferError("REVERSE_PROJECT_ID_INVALID")
        try:
            async with asyncio.timeout(self.backend_timeout_seconds):
                association = await self.native_projects.resolve_owned_project(
                    invocation, native_project_id
                )
        except Exception as exc:
            raise ProjectReverseTransferError("REVERSE_PROJECT_ACCESS_UNAVAILABLE") from exc
        if (
            not isinstance(association, GhidraProjectAssociation)
            or association.platform_project_id != invocation.project_id
            or association.native_ghidra_project_id != native_project_id
        ):
            raise ProjectReverseTransferError("REVERSE_PROJECT_ACCESS_DENIED")
        await self.authority.require(invocation, "reverse.read")
        return ProjectReverseAssociationView(
            platform_project_id=invocation.project_id,
            native_ghidra_project_id=native_project_id,
        )

    async def operation_metadata(
        self,
        invocation: ProjectInvocation,
        *,
        operation_uuid: UUID,
        native_project_id: str,
    ) -> ProjectReverseOperationView:
        """Ledger/native evidence only; UNKNOWN is not imported/not-imported."""
        if self.ledger is None:
            raise ProjectReverseTransferError("REVERSE_DURABLE_LEDGER_REQUIRED")
        association = await self.association_metadata(
            invocation, native_project_id=native_project_id
        )
        if not isinstance(operation_uuid, UUID) or operation_uuid.version != 4:
            raise ProjectReverseTransferError("REVERSE_OPERATION_UUID_INVALID")
        permit = await self.authority.require(invocation, "reverse.read")
        try:
            async with asyncio.timeout(self.backend_timeout_seconds):
                outcome = await self.ledger.reconcile_unknown(
                    project_id=invocation.project_id, operation_uuid=operation_uuid
                )
        except Exception as exc:
            raise ProjectReverseTransferError("REVERSE_LEDGER_UNAVAILABLE") from exc
        if (
            not isinstance(outcome, NativeImportReconciliation)
            or outcome.identity.operation_uuid != operation_uuid
            or outcome.identity.project_id != association.platform_project_id
            or outcome.identity.native_project_id != native_project_id
            or outcome.identity.actor_id != permit.actor_id
            or outcome.identity.session_uuid != permit.session_uuid
            or not outcome.native_evidence_verified
            or outcome.revision < 1
            or outcome.state not in {"recorded", "unknown", "no_effect"}
            or (outcome.state == "recorded" and not outcome.result_sha256)
        ):
            raise ProjectReverseTransferError("REVERSE_LEDGER_EVIDENCE_INVALID")
        return ProjectReverseOperationView(
            platform_project_id=invocation.project_id,
            native_ghidra_project_id=native_project_id,
            operation_uuid=operation_uuid,
            state=outcome.state,
            source_sha256=outcome.identity.source_sha256,
            source_bytes=outcome.identity.size_bytes,
            native_evidence_verified=True,
            result_sha256=outcome.result_sha256,
        )

    async def reconcile_import(
        self,
        invocation: ProjectInvocation,
        *,
        operation_uuid: UUID,
        native_project_id: str,
    ) -> NativeImportReconciliation:
        """Read trusted native evidence, never retry or delete a Ghidra artifact.

        A lost HTTP response is not evidence that import failed. `no_effect`
        requires an explicit check of native Project contents from Backend's
        ledger worker; an absent DB row alone cannot establish it.
        """
        if self.ledger is None or self.native_projects is None:
            raise ProjectReverseTransferError("REVERSE_DURABLE_LEDGER_REQUIRED")
        if not isinstance(operation_uuid, UUID) or operation_uuid.version != 4:
            raise ProjectReverseTransferError("REVERSE_OPERATION_UUID_INVALID")
        permit = await self.authority.require(invocation, "reverse.import")
        association = await self.native_projects.resolve_owned_project(
            invocation, native_project_id
        )
        if (
            association.platform_project_id != invocation.project_id
            or association.native_ghidra_project_id != native_project_id
        ):
            raise ProjectReverseTransferError("REVERSE_PROJECT_ACCESS_DENIED")
        try:
            async with asyncio.timeout(self.backend_timeout_seconds):
                result = await self.ledger.reconcile_unknown(
                    project_id=invocation.project_id, operation_uuid=operation_uuid
                )
        except Exception as exc:
            raise ProjectReverseTransferError("REVERSE_RECONCILIATION_UNAVAILABLE") from exc
        if (
            not isinstance(result, NativeImportReconciliation)
            or result.identity.operation_uuid != operation_uuid
            or result.identity.actor_id != permit.actor_id
            or result.identity.project_id != invocation.project_id
            or result.identity.native_project_id != native_project_id
            or result.identity.session_uuid != invocation.session_uuid
            or result.revision < 1
            or not result.native_evidence_verified
            or result.state not in {"recorded", "unknown", "no_effect"}
            or (result.state == "recorded" and not result.result_sha256)
        ):
            raise ProjectReverseTransferError("REVERSE_RECONCILIATION_UNVERIFIED")
        return result

    async def import_file(
        self,
        invocation: ProjectInvocation,
        *,
        native_project_id: str,
        source_path: str,
        auto_analyze: bool = True,
        operation_uuid: UUID | None = None,
    ) -> ProjectReverseImportResult:
        if (
            self.ledger is None
            or not isinstance(operation_uuid, UUID)
            or operation_uuid.version != 4
        ):
            raise ProjectReverseTransferError("REVERSE_DURABLE_LEDGER_REQUIRED")
        permit = await self.authority.require(invocation, "reverse.import")
        assert self.ledger is not None and operation_uuid is not None
        if self.native_projects is None or self.backend_call is None or self.stage_verifier is None:
            raise ProjectReverseTransferError("REVERSE_CONTRACT_UNAVAILABLE")
        if not valid_project_revision(permit.project_access_revision):
            raise ProjectReverseTransferError("REVERSE_PROJECT_FENCE_UNAVAILABLE")
        if not native_project_id or any(ord(char) < 32 for char in native_project_id):
            raise ProjectReverseTransferError("REVERSE_PROJECT_ID_INVALID")
        association = await self.native_projects.resolve_owned_project(
            invocation, native_project_id
        )
        if (
            association.platform_project_id != invocation.project_id
            or association.native_ghidra_project_id != native_project_id
        ):
            raise ProjectReverseTransferError("REVERSE_PROJECT_ACCESS_DENIED")
        # Files read and Reverse import are independent grants. An anonymous
        # O_TMPFILE snapshot avoids holding the whole firmware blob in RAM and
        # preserves the exact sha256/size during a separate native import.
        file_name = PurePosixPath(source_path).name
        if file_name in {"", ".", ".."}:
            raise ProjectReverseTransferError("REVERSE_FILE_INVALID")
        async with self.files.open_snapshot(
            invocation, source_path, chunk_bytes=self.chunk_bytes
        ) as snapshot:
            if snapshot.project_id != invocation.project_id:
                raise ProjectReverseTransferError("REVERSE_SOURCE_PROJECT_MISMATCH")
            identity = NativeImportIdentity(
                operation_uuid=operation_uuid,
                actor_id=permit.actor_id,
                project_id=invocation.project_id,
                session_uuid=invocation.session_uuid,
                native_project_id=native_project_id,
                source_sha256=snapshot.sha256,
                size_bytes=snapshot.size_bytes,
                auto_analyze=auto_analyze,
            )
            try:
                async with asyncio.timeout(self.backend_timeout_seconds):
                    claim = await self.ledger.claim(identity)
            except Exception as exc:
                raise ProjectReverseTransferError("REVERSE_LEDGER_UNAVAILABLE") from exc
            if (
                not isinstance(claim, NativeImportClaim)
                or claim.identity != identity
                or claim.revision < 1
            ):
                raise ProjectReverseTransferError("REVERSE_LEDGER_INVALID")
            if claim.state != "claimed":
                raise ProjectReverseTransferError("REVERSE_IMPORT_OUTCOME_REQUIRES_RECONCILIATION")

            dispatched = False
            confirmed = False
            # Even native staging creates external state. Its HTTP response
            # can be lost after remote acceptance; do not leave a claim in a
            # clean `claimed` state after such an ambiguous attempt.
            try:
                begun = await self._call(
                    "artifact_stage_begin",
                    {
                        "project_id": native_project_id,
                        "name": file_name,
                        "size_bytes": snapshot.size_bytes,
                        "sha256": snapshot.sha256,
                    },
                )
            except BaseException:
                with suppress(Exception):
                    async with asyncio.timeout(self.backend_timeout_seconds):
                        await self.ledger.record_unknown(claim)
                raise
            stage_id = begun.get("stage_id")
            if not isinstance(stage_id, str) or not 1 <= len(stage_id) <= 256:
                with suppress(Exception):
                    async with asyncio.timeout(self.backend_timeout_seconds):
                        await self.ledger.record_unknown(claim)
                raise ProjectReverseTransferError("REVERSE_STAGE_INVALID")
            cleanup_failed = False
            imported: JsonObject | None = None
            try:
                offset = 0
                while offset < snapshot.size_bytes:
                    chunk = await self.files.read_snapshot_chunk(
                        invocation, snapshot, offset=offset, length=self.chunk_bytes
                    )
                    if not chunk:
                        raise ProjectReverseTransferError("REVERSE_SNAPSHOT_TRUNCATED")
                    result = await self._call(
                        "artifact_stage_write",
                        {
                            "project_id": native_project_id,
                            "stage_id": stage_id,
                            "offset": offset,
                            "data_base64": base64.b64encode(chunk).decode("ascii"),
                        },
                    )
                    expected = offset + len(chunk)
                    if result.get("next_offset") != expected:
                        raise ProjectReverseTransferError("REVERSE_STAGE_OFFSET_INVALID")
                    offset = expected
                staged = await self._call(
                    "artifact_stage_finish",
                    {"project_id": native_project_id, "stage_id": stage_id},
                )
                native_path = staged.get("path")
                if not isinstance(native_path, str) or not native_path:
                    raise ProjectReverseTransferError("REVERSE_STAGE_PATH_INVALID")
                # A Backend-owned Ghidra storage verifier must confirm the
                # returned path refers to THIS staged file inside THIS native
                # Ghidra project, not an arbitrary client/SDK filesystem path.
                assert self.stage_verifier is not None
                try:
                    async with asyncio.timeout(self.backend_timeout_seconds):
                        stage_attestation = await self.stage_verifier.verify_native_stage(
                            invocation,
                            permit=permit,
                            native_project_id=native_project_id,
                            stage_id=stage_id,
                            native_path=native_path,
                            source_sha256=snapshot.sha256,
                            size_bytes=snapshot.size_bytes,
                        )
                except Exception as exc:
                    raise ProjectReverseTransferError(
                        "REVERSE_STAGE_PROVENANCE_UNAVAILABLE"
                    ) from exc
                if (
                    not isinstance(stage_attestation, NativeStagingAttestation)
                    or stage_attestation.platform_project_id != invocation.project_id
                    or stage_attestation.agent_session_uuid != invocation.session_uuid
                    or stage_attestation.actor_id != permit.actor_id
                    or stage_attestation.project_access_revision != permit.project_access_revision
                    or stage_attestation.native_project_id != native_project_id
                    or stage_attestation.stage_id != stage_id
                    or stage_attestation.native_stage_path != native_path
                    or stage_attestation.source_sha256 != snapshot.sha256
                    or stage_attestation.size_bytes != snapshot.size_bytes
                    or not isinstance(stage_attestation.expires_at, datetime)
                    or stage_attestation.expires_at.tzinfo is None
                    or stage_attestation.expires_at <= datetime.now(UTC)
                ):
                    raise ProjectReverseTransferError("REVERSE_STAGE_PROVENANCE_INVALID")
                # Import is the irreversible boundary. Refresh Project/session
                # grants and native Ghidra ownership after a long upload.
                fresh = await self.authority.require(invocation, "reverse.import")
                if (
                    fresh.actor_id != permit.actor_id
                    or fresh.project_access_revision != permit.project_access_revision
                    or fresh.project_owner_id != permit.project_owner_id
                    or fresh.project_owner_scope != permit.project_owner_scope
                ):
                    raise ProjectReverseTransferError("REVERSE_ACCESS_STALE")
                current = await self.native_projects.resolve_owned_project(
                    invocation, native_project_id
                )
                if (
                    current.platform_project_id != invocation.project_id
                    or current.native_ghidra_project_id != native_project_id
                ):
                    raise ProjectReverseTransferError("REVERSE_PROJECT_ACCESS_DENIED")
                try:
                    async with asyncio.timeout(self.backend_timeout_seconds):
                        await self.ledger.mark_dispatched(claim)
                except Exception as exc:
                    raise ProjectReverseTransferError("REVERSE_LEDGER_UNCERTAIN") from exc
                dispatched = True
                try:
                    imported = await self._call(
                        "import_file",
                        {
                            "project_id": native_project_id,
                            "file_path": native_path,
                            "project_folder": "/",
                            "language": "",
                            "compiler_spec": "",
                            "auto_analyze": auto_analyze,
                        },
                    )
                    result_hash = hashlib.sha256(
                        json.dumps(imported, sort_keys=True, allow_nan=False).encode()
                    ).hexdigest()
                    async with asyncio.timeout(self.backend_timeout_seconds):
                        await self.ledger.record_success(claim, result_sha256=result_hash)
                    confirmed = True
                except asyncio.CancelledError:
                    # A client disconnect cannot prove that native Ghidra
                    # aborted the import. Keep the staging path for reconcile.
                    with suppress(Exception):
                        async with asyncio.timeout(self.backend_timeout_seconds):
                            await self.ledger.record_unknown(claim)
                    raise
                except Exception as exc:
                    with suppress(Exception):
                        async with asyncio.timeout(self.backend_timeout_seconds):
                            await self.ledger.record_unknown(claim)
                    raise ProjectReverseTransferError("REVERSE_IMPORT_OUTCOME_UNKNOWN") from exc
            except BaseException:
                if not dispatched:
                    # Staging may already have been accepted by the native
                    # service, or the ledger's dispatch state may be unknown.
                    # A durable reconciliation is safer than claiming it is
                    # unambiguously retryable after client cancellation.
                    with suppress(Exception):
                        async with asyncio.timeout(self.backend_timeout_seconds):
                            await self.ledger.record_unknown(claim)
                raise
            finally:
                # An import with unknown outcome may still be using the staged
                # path. Only discard staging before dispatch or after durable
                # acknowledgement of the completed native operation.
                if not dispatched or confirmed:
                    try:
                        await self._call(
                            "artifact_stage_cancel",
                            {"project_id": native_project_id, "stage_id": stage_id},
                        )
                    except Exception:
                        cleanup_failed = True
            if imported is None:
                raise ProjectReverseTransferError("REVERSE_IMPORT_FAILED")
            return ProjectReverseImportResult(
                platform_project_id=invocation.project_id,
                native_ghidra_project_id=native_project_id,
                source_path=source_path,
                source_sha256=snapshot.sha256,
                size_bytes=snapshot.size_bytes,
                response=imported,
                staging_cleanup_failed=cleanup_failed,
            )
