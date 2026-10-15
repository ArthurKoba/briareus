"""Strict binding of authenticated private Access replies to one native read.

This decoder is NOT transport authentication or a permission issuer. Only
an independently authenticated Files/Access adapter may pass replies here;
the original Rauthy token, phase-specific nonce and actual root mapping
must be checked by their owners. Never accept this JSON from an MCP caller.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from ._native_read import NativeFilesReadRequest
from ._read_adapter import FilesMcpReadUnavailable

ReadPhase = Literal["before_read", "after_read"]
READ_DECISION_PATH = "/internal/v1/authorization/files/read-decision"
_PROTOCOL = "files-read-decision-v1"
_REPLY_KEYS = frozenset(
    {
        "protocol",
        "allowed",
        "operation_uuid",
        "phase",
        "actor_uuid",
        "project_uuid",
        "agent_session_uuid",
        "hand",
        "tool",
        "action",
        "resource",
        "grant_revision",
        "resource_revision",
        "max_bytes",
        "checked_at",
        "expires_at",
    }
)


@dataclass(frozen=True, slots=True)
class FilesReadDecisionRequest:
    request: NativeFilesReadRequest
    resource_revision: int
    phase: ReadPhase

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request, NativeFilesReadRequest)
            or type(self.resource_revision) is not int
            or not 1 <= self.resource_revision <= 2**63 - 1
            or self.phase not in {"before_read", "after_read"}
        ):
            raise FilesMcpReadUnavailable("FILES_DECISION_REQUEST_INVALID")

    def wire_body(self) -> bytes:
        request = self.request
        return json.dumps(
            {
                "protocol": _PROTOCOL,
                "operation_uuid": str(request.request_uuid),
                "phase": self.phase,
                "project_uuid": str(request.project_uuid),
                "agent_session_uuid": str(request.agent_session_uuid),
                "expected_grant_revision": request.expected_grant_revision,
                "expected_resource_revision": self.resource_revision,
                "max_bytes": request.arguments.max_bytes,
                "hand": "files",
                "tool": "read_file",
                "action": "files.read",
                "resource": request.selector.decision_resource(),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")


@dataclass(frozen=True, slots=True)
class FilesReadDecisionReceipt:
    """Validated data from a private reply, not a transferable signed token."""

    command: FilesReadDecisionRequest
    actor_uuid: UUID
    checked_at: datetime
    expires_at: datetime

    def final_deadline(self, previous: FilesReadDecisionReceipt, *, now: datetime) -> datetime:
        if (
            self.command.phase != "after_read"
            or previous.command.phase != "before_read"
            or self.command.request != previous.command.request
            or self.command.resource_revision != previous.command.resource_revision
            or self.actor_uuid != previous.actor_uuid
            or self.checked_at < previous.checked_at
            or now.tzinfo is None
            or not self.checked_at <= now < min(self.expires_at, previous.expires_at)
        ):
            raise FilesMcpReadUnavailable("FILES_DECISION_PHASE_BINDING_INVALID")
        return min(self.expires_at, previous.expires_at)


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("duplicate Access reply field")
        data[key] = value
    return data


def decode_private_read_decision(
    *,
    command: FilesReadDecisionRequest,
    status: int,
    body: bytes,
    expected_actor_uuid: UUID,
    now: datetime | None = None,
) -> FilesReadDecisionReceipt:
    """Check exact original request + verified actor supplied by private peer.

    No raw bearer/JWKS/HTTP headers belong here. The adapter MUST reject
    unverified HTTP origins or stale body-bound nonces before this decoder.
    Both phases use new authenticated requests, not cached receipt reuse.
    """
    try:
        if (
            not isinstance(command, FilesReadDecisionRequest)
            or type(status) is not int
            or status != 200
            or type(body) is not bytes
            or not 0 < len(body) <= 8192
            or not isinstance(expected_actor_uuid, UUID)
            or expected_actor_uuid.version != 4
        ):
            raise ValueError("private reply shape")
        data = json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=_unique_fields)
        if type(data) is not dict or set(data) != _REPLY_KEYS or data["allowed"] is not True:
            raise ValueError("invalid Access read reply")
        request = command.request
        expected = {
            "protocol": _PROTOCOL,
            "operation_uuid": str(request.request_uuid),
            "phase": command.phase,
            "actor_uuid": str(expected_actor_uuid),
            "project_uuid": str(request.project_uuid),
            "agent_session_uuid": str(request.agent_session_uuid),
            "hand": "files",
            "tool": "read_file",
            "action": "files.read",
            "resource": request.selector.decision_resource(),
            "grant_revision": request.expected_grant_revision,
            "resource_revision": command.resource_revision,
            "max_bytes": request.arguments.max_bytes,
        }
        if any(
            data[name] != value or type(data[name]) is not type(value)
            for name, value in expected.items()
        ):
            raise ValueError("original Files read binding changed")
        if not isinstance(data["checked_at"], str) or not isinstance(data["expires_at"], str):
            raise ValueError("invalid Access timestamps")
        checked = datetime.fromisoformat(data["checked_at"])
        expires = datetime.fromisoformat(data["expires_at"])
        current = datetime.now(UTC) if now is None else now
        if (
            checked.tzinfo is None
            or expires.tzinfo is None
            or current.tzinfo is None
            or not checked <= current < expires <= checked + timedelta(seconds=5)
        ):
            raise ValueError("stale or excessive read proof lifetime")
        return FilesReadDecisionReceipt(command, expected_actor_uuid, checked, expires)
    except (TypeError, ValueError, UnicodeError, KeyError, RecursionError):
        raise FilesMcpReadUnavailable("FILES_DECISION_REPLY_INVALID") from None
