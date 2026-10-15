"""Authenticated, exact-body signed Access management command transport.

The browser owns neither service credential nor User identity. A real private
peer signs a short-lived delegated Rauthy/Platform actor AND the exact command
hash. The destination is fixed; the Authorization service independently checks
the signature, peer and current owner SQL/idempotent state before any mutation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from ._access_management_client import (
    TrustedAccessPeerPort,
    VerifiedAccessTransport,
)
from ._oidc_approvals import (
    _OPERATIONS,
    ApprovalSnapshot,
    CurrentSessionSnapshot,
    GrantSnapshot,
    OpenSessionSnapshot,
    OwnerManagementConflict,
    OwnerManagementDenied,
    OwnerManagementInvalidInput,
    OwnerManagementUnavailable,
    ScopedEffectRequest,
)

_ACTIONS: dict[str, str] = {
    "open": "session.open",
    "request": "session.request_elevation",
    "resolve": "session.resolve_elevation",
    "revoke": "session.revoke",
}
_ROUTES: dict[str, str] = {
    "open": "http://briareus-authorization:8000/internal/v1/authorization/sessions/open",
    "request": "http://briareus-authorization:8000/internal/v1/authorization/approvals/request",
    "resolve": "http://briareus-authorization:8000/internal/v1/authorization/approvals/resolve",
    "revoke": "http://briareus-authorization:8000/internal/v1/authorization/sessions/revoke",
}
_MAX_BYTES = 48_000
_OWNER_DEADLINE_SECONDS = 12


def _unique_receipt_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """No last-value-wins from an ambiguously encoded private owner reply."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate private Access receipt field")
        result[key] = value
    return result


def _strict_receipt(raw: bytes) -> object:
    try:
        return json.loads(raw, object_pairs_hook=_unique_receipt_pairs)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise OwnerManagementUnavailable("ambiguous private Access owner receipt") from None


@dataclass(frozen=True, slots=True)
class VerifiedAccessWriteDelegation:
    """Signed delegation, not a browser claim or a random authorization header."""

    issuer: Literal["rauthy"]
    actor_uuid: UUID
    project_uuid: UUID
    operation_uuid: UUID
    action: Literal[
        "session.open", "session.request_elevation", "session.resolve_elevation", "session.revoke"
    ]
    body_sha256: str
    bearer: SecretStr
    audience: Literal["briareus:access"]
    expires_at: datetime


class TrustedAccessWritePeerPort(TrustedAccessPeerPort, Protocol):
    async def signed_command_delegation(
        self,
        *,
        actor_uuid: UUID,
        project_uuid: UUID,
        operation_uuid: UUID,
        action: str,
        body_sha256: str,
    ) -> VerifiedAccessWriteDelegation:
        """Independently verify live Rauthy User/Project then sign exact command."""
        ...


class _OpenReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_uuid: UUID
    project_uuid: UUID
    revision: int = Field(strict=True, ge=1)
    status: Literal["active"]
    is_elevated: Literal[False]
    elevation_policy: Literal["fixed", "requestable"]
    hard_expires_at: datetime
    operations: tuple[str, ...]
    resources: tuple[dict[str, object], ...]


class _ApprovalReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    requested_by_user_uuid: UUID
    status: Literal["pending", "approved", "rejected"]
    version: int = Field(strict=True, ge=1)
    requested_operations: tuple[str, ...] = Field(min_length=1, max_length=32)
    requested_resources: tuple[dict[str, object], ...] = Field(max_length=32)
    requested_expires_at: datetime
    resolved_by_user_uuid: UUID | None = None
    issued_session_uuid: UUID | None = None


class _RevokeReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_uuid: UUID
    project_uuid: UUID
    status: Literal["revoked"]
    revision: int = Field(strict=True, ge=2)


class PrivateAccessManagementWriter:
    def __init__(self, *, trusted_peer: TrustedAccessWritePeerPort) -> None:
        if trusted_peer is None:
            raise ValueError("independent signed Access write peer required")
        self._peer = trusted_peer

    async def _write(
        self,
        *,
        action: Literal["open", "request", "resolve", "revoke"],
        actor: UUID,
        project: UUID,
        operation: UUID,
        fields: dict[str, object],
        expected_code: int,
    ) -> bytes:
        if (
            not isinstance(actor, UUID)
            or actor.version != 4
            or not isinstance(project, UUID)
            or project.version != 4
            or not isinstance(operation, UUID)
            or operation.version != 4
        ):
            raise OwnerManagementDenied("invalid authoritative Access selector")
        command = {
            "project_uuid": str(project),
            "operation_uuid": str(operation),
            **fields,
        }
        # Stable canonical bytes avoid signature/authorization ambiguity.
        try:
            serialized = json.dumps(
                command,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
        except (TypeError, ValueError, UnicodeEncodeError):
            raise OwnerManagementDenied("invalid Access owner command") from None
        if not 1 <= len(serialized) <= 32_768:
            raise OwnerManagementDenied("Access command out of bounds")
        body_hash = hashlib.sha256(serialized).hexdigest()
        deadline = asyncio.get_running_loop().time() + _OWNER_DEADLINE_SECONDS
        try:
            async with asyncio.timeout_at(deadline):
                transport = await self._peer.current_transport()
                delegated = await self._peer.signed_command_delegation(
                    actor_uuid=actor,
                    project_uuid=project,
                    operation_uuid=operation,
                    action=_ACTIONS[action],
                    body_sha256=body_hash,
                )
        except Exception:
            raise OwnerManagementUnavailable("signed owner transport unavailable") from None
        now = datetime.now(UTC)
        if (
            not isinstance(transport, VerifiedAccessTransport)
            or transport.mode not in {"mtls", "unix-peer"}
            or transport.audience != "briareus:access"
            or not isinstance(transport.expires_at, datetime)
            or transport.expires_at.tzinfo is None
            or not now < transport.expires_at <= now + timedelta(seconds=30)
            or not isinstance(delegated, VerifiedAccessWriteDelegation)
            or delegated.issuer != "rauthy"
            or delegated.actor_uuid != actor
            or delegated.project_uuid != project
            or delegated.operation_uuid != operation
            or delegated.action != _ACTIONS[action]
            or delegated.body_sha256 != body_hash
            or delegated.audience != "briareus:access"
            or not isinstance(delegated.expires_at, datetime)
            or delegated.expires_at.tzinfo is None
            or not now < delegated.expires_at <= transport.expires_at
        ):
            raise OwnerManagementUnavailable("private Access command not attested")
        bearer = delegated.bearer.get_secret_value()
        if (
            not 40 <= len(bearer) <= 8192
            or not bearer.isascii()
            or any(char.isspace() for char in bearer)
        ):
            raise OwnerManagementUnavailable("private signed Access bearer invalid")

        try:
            async with (
                asyncio.timeout_at(deadline),
                transport.client.stream(
                    "POST",
                    _ROUTES[action],
                    content=serialized,
                    headers={
                        "Authorization": "Bearer " + bearer,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Operation-UUID": str(operation),
                        "Idempotency-Key": str(operation),
                    },
                    follow_redirects=False,
                ) as response,
            ):
                if response.status_code in {401, 403}:
                    raise OwnerManagementDenied("Authorization owner denied Access command")
                if response.status_code == 409:
                    raise OwnerManagementConflict("current grant revision conflict")
                if response.status_code == 422:
                    raise OwnerManagementInvalidInput("private Access command scope invalid")
                if response.status_code != expected_code:
                    raise OwnerManagementUnavailable("Authorization owner did not commit command")
                if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                    raise OwnerManagementUnavailable("invalid owner response MIME")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > _MAX_BYTES:
                        raise OwnerManagementUnavailable("owner response exceeds limit")
                    raw.extend(chunk)
        except (httpx.HTTPError, TimeoutError):
            raise OwnerManagementUnavailable("Access write transport unavailable") from None
        if delegated.expires_at <= datetime.now(UTC):
            raise OwnerManagementUnavailable("Access owner delegation expired during write")
        return bytes(raw)

    @staticmethod
    def _approval(
        raw: bytes,
        *,
        project: UUID,
        actor: UUID,
        state: str,
        expected_approval: UUID | None = None,
    ) -> ApprovalSnapshot:
        try:
            item = _ApprovalReceipt.model_validate(_strict_receipt(raw))
        except (ValidationError, ValueError):
            raise OwnerManagementUnavailable("Authorization approval response invalid") from None
        if (
            item.project_uuid != project
            or item.status != state
            or item.id.version != 4
            or item.agent_session_uuid.version != 4
            or item.requested_by_user_uuid.version != 4
            or item.requested_expires_at.tzinfo is None
            or (expected_approval is not None and item.id != expected_approval)
            or (
                state == "pending"
                and (
                    item.version != 1
                    or item.requested_by_user_uuid != actor
                    or item.resolved_by_user_uuid is not None
                    or item.issued_session_uuid is not None
                )
            )
            or (
                state != "pending"
                and (
                    item.version < 2
                    or item.requested_by_user_uuid == actor
                    or item.resolved_by_user_uuid != actor
                    or (state == "approved") != (item.issued_session_uuid is not None)
                )
            )
            or (
                item.issued_session_uuid is not None
                and (
                    item.issued_session_uuid.version != 4
                    or item.issued_session_uuid == item.agent_session_uuid
                )
            )
            or len(set(item.requested_operations)) != len(item.requested_operations)
            or not set(item.requested_operations) <= _OPERATIONS
        ):
            raise OwnerManagementUnavailable("Authorization approved a foreign scope")
        try:
            effects = tuple(ScopedEffectRequest.model_validate(v) for v in item.requested_resources)
        except ValueError:
            raise OwnerManagementUnavailable(
                "Authorization approval resource scope invalid"
            ) from None
        if len(set(effects)) != len(effects) or any(
            effect.action not in item.requested_operations for effect in effects
        ):
            raise OwnerManagementUnavailable("Authorization approval resource scope mismatch")
        return ApprovalSnapshot(
            approval_uuid=item.id,
            project_uuid=item.project_uuid,
            agent_session_uuid=item.agent_session_uuid,
            requested_by_user_uuid=item.requested_by_user_uuid,
            status=item.status,
            version=item.version,
            requested_operations=item.requested_operations,
            requested_resources=item.requested_resources,
            requested_expires_at=item.requested_expires_at,
            resolved_by_user_uuid=item.resolved_by_user_uuid,
            issued_session_uuid=item.issued_session_uuid,
        )

    async def open_normal(
        self,
        *,
        actor: UUID,
        project: UUID,
        elevation_policy: Literal["fixed", "requestable"],
        label: str | None,
        operation: UUID,
    ) -> OpenSessionSnapshot:
        raw = await self._write(
            action="open",
            actor=actor,
            project=project,
            operation=operation,
            fields={"elevation_policy": elevation_policy, "label": label},
            expected_code=201,
        )
        try:
            receipt = _OpenReceipt.model_validate(_strict_receipt(raw))
        except (ValidationError, ValueError):
            raise OwnerManagementUnavailable("Access owner opening receipt invalid") from None
        now = datetime.now(UTC)
        if (
            receipt.session_uuid.version != 4
            or receipt.project_uuid != project
            or receipt.revision != 1
            or receipt.elevation_policy != elevation_policy
            or receipt.hard_expires_at.tzinfo is None
            or not now < receipt.hard_expires_at <= now + timedelta(hours=24)
            or receipt.operations != ("files.read", "project.metadata.read")
            or receipt.resources
        ):
            raise OwnerManagementUnavailable("Access owner opened unauthorized session")
        return OpenSessionSnapshot(
            session_uuid=receipt.session_uuid,
            project_uuid=project,
            revision=receipt.revision,
            status="active",
            is_elevated=False,
            elevation_policy=receipt.elevation_policy,
            hard_expires_at=receipt.hard_expires_at,
            operations=receipt.operations,
            resources=receipt.resources,
        )

    async def request_elevation(
        self,
        *,
        actor: UUID,
        project: UUID,
        session: UUID,
        operations: tuple[str, ...],
        resources: tuple[dict[str, object], ...],
        seconds: int,
        expected_grant_revision: int,
        operation: UUID,
    ) -> ApprovalSnapshot:
        raw = await self._write(
            action="request",
            actor=actor,
            project=project,
            operation=operation,
            fields={
                "agent_session_uuid": str(session),
                "operations": list(operations),
                "resources": list(resources),
                "seconds": seconds,
                "expected_grant_revision": expected_grant_revision,
            },
            expected_code=202,
        )
        result = self._approval(raw, project=project, actor=actor, state="pending")
        try:
            expected_effects = tuple(ScopedEffectRequest.model_validate(item) for item in resources)
            received_effects = tuple(
                ScopedEffectRequest.model_validate(item) for item in result.requested_resources
            )
        except ValueError:
            raise OwnerManagementUnavailable("Access request resource scope invalid") from None
        if (
            result.agent_session_uuid != session
            or result.approval_uuid != operation
            or set(result.requested_operations) != set(operations)
            or len(result.requested_operations) != len(operations)
            or len(received_effects) != len(expected_effects)
            or set(received_effects) != set(expected_effects)
        ):
            raise OwnerManagementUnavailable("Access owner request selector mismatch")
        return result

    async def resolve_elevation(
        self,
        *,
        actor: UUID,
        project: UUID,
        approval: UUID,
        expected_version: int,
        approve: bool,
        allowed_operations: tuple[str, ...] | None,
        operation: UUID,
    ) -> ApprovalSnapshot:
        raw = await self._write(
            action="resolve",
            actor=actor,
            project=project,
            operation=operation,
            fields={
                "approval_uuid": str(approval),
                "expected_approval_version": expected_version,
                "approve": approve,
                "allowed_operations": list(allowed_operations)
                if allowed_operations is not None
                else None,
            },
            expected_code=200,
        )
        result = self._approval(
            raw,
            project=project,
            actor=actor,
            state="approved" if approve else "rejected",
            expected_approval=approval,
        )
        if result.version != expected_version + 1:
            raise OwnerManagementUnavailable("Authorization approval revision mismatch")
        if allowed_operations is not None and not set(allowed_operations) <= set(
            result.requested_operations
        ):
            raise OwnerManagementUnavailable("Authorization approval expanded operation set")
        return result

    async def revoke_session(
        self,
        *,
        actor: UUID,
        project: UUID,
        session: UUID,
        expected_revision: int,
        operation: UUID,
    ) -> GrantSnapshot:
        raw = await self._write(
            action="revoke",
            actor=actor,
            project=project,
            operation=operation,
            fields={
                "agent_session_uuid": str(session),
                "expected_grant_revision": expected_revision,
            },
            expected_code=200,
        )
        try:
            item = _RevokeReceipt.model_validate(_strict_receipt(raw))
        except (ValidationError, ValueError):
            raise OwnerManagementUnavailable("Authorization revoke receipt invalid") from None
        if (
            item.project_uuid != project
            or item.session_uuid != session
            or item.revision != expected_revision + 1
            or item.session_uuid.version != 4
        ):
            raise OwnerManagementUnavailable("Authorization revoke scope mismatch")
        return GrantSnapshot(
            session_uuid=item.session_uuid,
            project_uuid=project,
            status="revoked",
            revision=item.revision,
        )


class PrivateAccessManagementBundle:
    """One injected verified peer for read AND signed write owner commands.

    Control Panel BFF accepts this as its ApprovalManagementPort. The same
    trusted factory must authenticate both user and service transport
    independently; no service transport is constructed from HTTP input.
    """

    def __init__(self, *, trusted_peer: TrustedAccessWritePeerPort) -> None:
        from ._access_management_client import PrivateAccessManagementClient

        if trusted_peer is None:
            raise ValueError("trusted read and write Access peer required")
        self._read = PrivateAccessManagementClient(trusted_peer=trusted_peer)
        self._write = PrivateAccessManagementWriter(trusted_peer=trusted_peer)

    async def list_approvals(
        self, *, actor: UUID, project: UUID, limit: int
    ) -> tuple[ApprovalSnapshot, ...]:
        return await self._read.list_approvals(actor=actor, project=project, limit=limit)

    async def open_normal(
        self,
        *,
        actor: UUID,
        project: UUID,
        elevation_policy: Literal["fixed", "requestable"],
        label: str | None,
        operation: UUID,
    ) -> OpenSessionSnapshot:
        return await self._write.open_normal(
            actor=actor,
            project=project,
            elevation_policy=elevation_policy,
            label=label,
            operation=operation,
        )

    async def list_sessions(
        self, *, actor: UUID, project: UUID, limit: int
    ) -> tuple[CurrentSessionSnapshot, ...]:
        return await self._read.list_sessions(actor=actor, project=project, limit=limit)

    async def get_session(
        self, *, actor: UUID, project: UUID, session: UUID
    ) -> CurrentSessionSnapshot:
        return await self._read.get_session(actor=actor, project=project, session=session)

    async def request_elevation(
        self,
        *,
        actor: UUID,
        project: UUID,
        session: UUID,
        operations: tuple[str, ...],
        resources: tuple[dict[str, object], ...],
        seconds: int,
        expected_grant_revision: int,
        operation: UUID,
    ) -> ApprovalSnapshot:
        return await self._write.request_elevation(
            actor=actor,
            project=project,
            session=session,
            operations=operations,
            resources=resources,
            seconds=seconds,
            expected_grant_revision=expected_grant_revision,
            operation=operation,
        )

    async def resolve_elevation(
        self,
        *,
        actor: UUID,
        project: UUID,
        approval: UUID,
        expected_version: int,
        approve: bool,
        allowed_operations: tuple[str, ...] | None,
        operation: UUID,
    ) -> ApprovalSnapshot:
        return await self._write.resolve_elevation(
            actor=actor,
            project=project,
            approval=approval,
            expected_version=expected_version,
            approve=approve,
            allowed_operations=allowed_operations,
            operation=operation,
        )

    async def revoke_session(
        self,
        *,
        actor: UUID,
        project: UUID,
        session: UUID,
        expected_revision: int,
        operation: UUID,
    ) -> GrantSnapshot:
        return await self._write.revoke_session(
            actor=actor,
            project=project,
            session=session,
            expected_revision=expected_revision,
            operation=operation,
        )
