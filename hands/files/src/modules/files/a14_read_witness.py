"""A14 Files read witness preflight: no native signer, SQL, or public tool.

This consumer can bind a separately trusted Files FileObject source and a C2
signed native FD witness. It only prepares the exact business payload that
Backend A14 must independently verify inside its Files-owner SQL transaction.
A prepared payload is NOT a read permit, credential, or OS authority.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.project_runtime import ProjectAccessDenied, ProjectInvocation, ProjectRuntimeAuthority
from modules.project_runtime.owner_authorization import VerifiedOwnerRecipient
from modules.project_runtime.owner_effects import OwnerEffectClient, OwnerEffectUnavailable

from .a6_signed import canonical_files_path, path_fingerprint
from .project_workspace import ProjectFileSnapshot


def _v4(value: UUID) -> bool:
    return isinstance(value, UUID) and value.version == 4


class CurrentCommittedFileObject(BaseModel):
    """Only a signed, current Files owner port may supply this projection."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    project_id: UUID
    file_id: UUID
    path_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_version: int = Field(ge=1)
    size_bytes: int = Field(ge=0, le=1048576)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inode_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def check_identity(self) -> CurrentCommittedFileObject:
        if not _v4(self.project_id) or not _v4(self.file_id):
            raise ValueError("current Files owner IDs must be UUIDv4")
        return self


class VerifiedNativeFileReadObservation(BaseModel):
    """Exactly the fields accepted by A14 VerifiedNativeFileReadObservation.

    Structural validation does NOT verify an OS signature. Only the injected
    trusted C2 native port below may return this after independently checking
    the signer, source descriptor, UID, private mount and operation recipient.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_uuid: UUID
    project_id: UUID
    file_id: UUID
    agent_session_uuid: UUID
    actor_user_id: UUID
    service_id: UUID
    instance_uuid: UUID
    path_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_version: int = Field(ge=1)
    size_bytes: int = Field(ge=0, le=1048576)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inode_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mount_scope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    verified_uid: int = Field(gt=0)
    observed_at: datetime

    @model_validator(mode="after")
    def check_identity_and_time(self) -> VerifiedNativeFileReadObservation:
        if (
            not all(
                _v4(value)
                for value in (
                    self.operation_uuid,
                    self.project_id,
                    self.file_id,
                    self.agent_session_uuid,
                    self.actor_user_id,
                    self.service_id,
                    self.instance_uuid,
                )
            )
            or self.observed_at.tzinfo is None
        ):
            raise ValueError("A14 native Files read signed source scope invalid")
        return self


class CurrentCommittedFileSourcePort(Protocol):
    """Independent signed Files-owner lookup, not an MCP/client FileObject."""

    async def verified_current_file(
        self,
        invocation: ProjectInvocation,
        *,
        path_digest: str,
        recipient: VerifiedOwnerRecipient,
    ) -> CurrentCommittedFileObject: ...


class TrustedNativeReadPort(Protocol):
    """Verify genuine C2 signed OS FD/UID/mount evidence without creating it."""

    async def verified_native_read(
        self,
        evidence: object,
        *,
        recipient: VerifiedOwnerRecipient,
        invocation: ProjectInvocation,
        snapshot: ProjectFileSnapshot,
    ) -> VerifiedNativeFileReadObservation: ...


@dataclass(frozen=True, slots=True)
class FilesReadBusinessPreimage:
    """Backend A14 canonical JSON body; NEVER a signed or completed receipt."""

    original_operation_uuid: UUID
    file_object: CurrentCommittedFileObject
    observation: VerifiedNativeFileReadObservation
    business_payload: dict[str, object]


class A14FilesReadPreflight:
    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        effects: OwnerEffectClient,
        *,
        files_source: CurrentCommittedFileSourcePort | None = None,
        native_verifier: TrustedNativeReadPort | None = None,
    ) -> None:
        self.authority = authority
        self.effects = effects
        self.files_source = files_source
        self.native_verifier = native_verifier

    async def prepare(
        self,
        invocation: ProjectInvocation,
        *,
        snapshot: ProjectFileSnapshot,
        evidence: object,
    ) -> FilesReadBusinessPreimage:
        """Check A14 original operation+native observation; do NOT return bytes.

        The Backend must independently verify the same opaque native evidence
        with its trusted read_observer in the Files-owner transaction, compare
        FileObject CAS/inode/content and return its separately signed result.
        No OwnerEffectClient call or public route is authorized here.
        """
        if self.files_source is None or self.native_verifier is None or evidence is None:
            raise OwnerEffectUnavailable("A14_FILES_NATIVE_C2_AND_OWNER_REQUIRED")
        scope = invocation.operation_scope
        if (
            scope is None
            or scope.action != "files.read"
            or scope.project_id != invocation.project_id
            or scope.agent_session_uuid != invocation.session_uuid
            or not _v4(scope.request_uuid)
            or not isinstance(snapshot, ProjectFileSnapshot)
            or snapshot._fd < 0
            or snapshot.signed_operation_uuid != scope.request_uuid
            or snapshot.size_bytes > 1048576
            or not snapshot.path
        ):
            raise OwnerEffectUnavailable("A14_FILES_ORIGINAL_SIGNED_SNAPSHOT_REQUIRED")
        initial = await self.authority.require(invocation, "files.read")
        if (
            snapshot.project_id != initial.project_id
            or snapshot.actor_id != initial.actor_id
            or snapshot.agent_session_uuid != initial.session_uuid
            or snapshot.project_access_revision != initial.project_access_revision
            or snapshot.signed_owner_fence != initial.owner_fence
            or snapshot.agent_session_version != initial.decision_version
        ):
            raise ProjectAccessDenied("A14_FILES_SNAPSHOT_GRANT_STALE")
        canonical = canonical_files_path(snapshot.path)
        path_digest = path_fingerprint(canonical)
        peer = await self.effects._recipient(invocation)
        assert self.files_source is not None and self.native_verifier is not None
        try:
            async with asyncio.timeout(min(5.0, self.effects.timeout_seconds)):
                current = await self.files_source.verified_current_file(
                    invocation, path_digest=path_digest, recipient=peer
                )
                observed = await self.native_verifier.verified_native_read(
                    evidence, recipient=peer, invocation=invocation, snapshot=snapshot
                )
        except Exception as exc:
            raise OwnerEffectUnavailable(
                "A14_FILES_READ_WITNESS_UNAVAILABLE", unknown=True
            ) from exc
        now = datetime.now(UTC)
        if (
            not isinstance(current, CurrentCommittedFileObject)
            or not isinstance(observed, VerifiedNativeFileReadObservation)
            or current.project_id != initial.project_id
            or current.path_digest != path_digest
            or current.size_bytes != snapshot.size_bytes
            or current.content_sha256 != snapshot.sha256
            or observed.operation_uuid != scope.request_uuid
            or observed.project_id != initial.project_id
            or observed.file_id != current.file_id
            or observed.agent_session_uuid != initial.session_uuid
            or observed.actor_user_id != initial.actor_id
            or observed.service_id != peer.service_id
            or observed.instance_uuid != peer.instance_uuid
            or observed.path_digest != path_digest
            or observed.file_version != current.file_version
            or observed.size_bytes != snapshot.size_bytes
            or observed.content_sha256 != snapshot.sha256
            or observed.inode_digest != current.inode_digest
            or not timedelta(0) <= now - observed.observed_at <= timedelta(seconds=5)
            or peer.expires_at <= now
        ):
            raise OwnerEffectUnavailable("A14_FILES_NATIVE_READ_SCOPE_CHANGED", unknown=True)
        try:
            async with asyncio.timeout(min(5.0, self.effects.timeout_seconds)):
                reread = await self.files_source.verified_current_file(
                    invocation, path_digest=path_digest, recipient=peer
                )
                fresh = await self.authority.require(invocation, "files.read")
        except Exception as exc:
            raise OwnerEffectUnavailable("A14_FILES_READ_REREAD_UNAVAILABLE", unknown=True) from exc
        if (
            reread != current
            or fresh.owner_fence != initial.owner_fence
            or fresh.project_access_revision != initial.project_access_revision
            or fresh.project_owner_scope != initial.project_owner_scope
            or fresh.project_owner_id != initial.project_owner_id
            or fresh.actor_id != initial.actor_id
            or fresh.session_uuid != initial.session_uuid
            or fresh.expires_at <= datetime.now(UTC)
            or datetime.now(UTC) - observed.observed_at > timedelta(seconds=5)
        ):
            raise OwnerEffectUnavailable("A14_FILES_READ_REVOKED_BEFORE_SQL", unknown=True)
        return FilesReadBusinessPreimage(
            original_operation_uuid=scope.request_uuid,
            file_object=current,
            observation=observed,
            business_payload={
                "file_id": str(current.file_id),
                "expected_file_version": current.file_version,
                "path_digest": path_digest,
                "service_id": str(peer.service_id),
                "instance_uuid": str(peer.instance_uuid),
                "native_observation": {
                    "content_sha256": observed.content_sha256,
                    "size_bytes": observed.size_bytes,
                    "inode_digest": observed.inode_digest,
                    "mount_scope_digest": observed.mount_scope_digest,
                    "verified_uid": observed.verified_uid,
                    "observed_at": observed.observed_at.isoformat(),
                },
            },
        )
