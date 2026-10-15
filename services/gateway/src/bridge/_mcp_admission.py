"""Coarse MCP connection admission against independent Authorization.

Incoming selectors are not identity proof. Only an independently attested
Authorization 200 with the exact Permit body may allow Gateway forwarding.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from starlette.requests import Request
from starlette.responses import JSONResponse

from .single_origin import MCP_MODULES

_HAND_TARGETS = {name: f"http://briareus-{name}:8000/mcp" for name in MCP_MODULES}
_DECISION_TIMEOUT_SECONDS = 5


@dataclass(frozen=True, slots=True)
class PrivateAdmissionReply:
    """HTTP status and bounded response from authenticated private transport."""

    status_code: int
    body: bytes


class TrustedGatewayDecisionPort(Protocol):
    """Real mTLS/Unix peer, exact decision bytes and nonce proof.

    A plain HTTP URL, caller Bearer, Docker DNS or untrusted header is not a
    service identity. No default implementation is supplied by Gateway.
    """

    async def decide(self, *, bearer: str, body: bytes) -> PrivateAdmissionReply: ...


class McpAdmissionRejected(Exception):
    """A bounded public transport rejection, never a Cedar decision."""

    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ConnectionAdmission:
    hand: str
    bearer: str
    project_uuid: UUID
    agent_session_uuid: UUID
    grant_revision: int

    @property
    def target(self) -> str:
        return _HAND_TARGETS[self.hand]

    def command(self) -> dict[str, str | int]:
        return {
            "project_uuid": str(self.project_uuid),
            "agent_session_uuid": str(self.agent_session_uuid),
            "action": "mcp.connect",
            "expected_grant_revision": self.grant_revision,
        }


def admission_error(code: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"code": code},
        status_code=status,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def _single_header(request: Request, name: str) -> str:
    values = request.headers.getlist(name)
    if len(values) != 1 or not values[0] or len(values[0]) > 128 or values[0].strip() != values[0]:
        raise McpAdmissionRejected("MCP_CONTEXT_INVALID", 400)
    return values[0]


def parse_connection_admission(request: Request) -> ConnectionAdmission:
    """Parse strictly bounded, *untrusted* selectors for the real PDP."""
    hand = request.url.path.removeprefix("/hands/").removesuffix("/mcp")
    canonical = f"/hands/{hand}/mcp"
    if (
        hand not in _HAND_TARGETS
        or request.url.path != canonical
        or request.scope.get("raw_path") != canonical.encode("ascii")
    ):
        # A path normalized from percent-encoding, dot segments or duplicate
        # separators is NOT the exact public MCP resource URI. Reject it
        # before consulting Authorization or passing a bearer to a Hand.
        raise McpAdmissionRejected("MCP_MODULE_UNKNOWN", 404)
    if request.scope.get("query_string", b"") != b"":
        raise McpAdmissionRejected("MCP_CONTEXT_INVALID", 400)
    if request.method != "POST":
        raise McpAdmissionRejected("MCP_METHOD_UNSUPPORTED", 405)
    if request.headers.getlist("cookie"):
        raise McpAdmissionRejected("MCP_COOKIE_NOT_ALLOWED", 400)
    authorizations = request.headers.getlist("authorization")
    if len(authorizations) != 1:
        raise McpAdmissionRejected("MCP_BEARER_REQUIRED", 401)
    bearer = authorizations[0]
    if (
        not bearer.startswith("Bearer ")
        or len(bearer) > 8192
        or bearer.count(" ") != 1
        or not bearer[7:]
        or any(char.isspace() for char in bearer[7:])
    ):
        raise McpAdmissionRejected("MCP_BEARER_REQUIRED", 401)
    try:
        project_text = _single_header(request, "x-briareus-project-uuid")
        session_text = _single_header(request, "x-briareus-agent-session-uuid")
        project_uuid = UUID(project_text)
        agent_session_uuid = UUID(session_text)
        raw_revision = _single_header(request, "x-briareus-grant-revision")
        if not raw_revision.isascii() or not raw_revision.isdecimal():
            raise ValueError("non-decimal grant revision")
        revision = int(raw_revision)
    except (ValueError, OverflowError) as exc:
        raise McpAdmissionRejected("MCP_CONTEXT_INVALID", 400) from exc
    if (
        project_uuid.version != 4
        or str(project_uuid) != project_text
        or agent_session_uuid.version != 4
        or str(agent_session_uuid) != session_text
        or not 1 <= revision <= 2**63 - 1
        or str(revision) != raw_revision
    ):
        raise McpAdmissionRejected("MCP_CONTEXT_INVALID", 400)
    return ConnectionAdmission(hand, bearer, project_uuid, agent_session_uuid, revision)


def _strict_permit_response(payload: bytes) -> bool:
    """Only exact typed JSON boolean Permit without duplicate keys admits MCP."""

    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate Permit field")
            result[key] = value
        return result

    if not payload or len(payload) > 4096:
        return False
    try:
        permit = json.loads(payload, object_pairs_hook=no_duplicates)
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(permit, dict) and set(permit) == {"allowed"} and permit["allowed"] is True


async def authorize_connection(
    private: TrustedGatewayDecisionPort | None, admission: ConnectionAdmission
) -> JSONResponse | None:
    """Only a real authenticated private peer may carry Bearer to Authorization."""
    if private is None:
        return admission_error("MCP_AUTHORIZATION_UNAVAILABLE", 503)
    try:
        wire = json.dumps(
            admission.command(), ensure_ascii=True, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if not 0 < len(wire) <= 8192:
            return admission_error("MCP_AUTHORIZATION_UNAVAILABLE", 503)
        decision = await asyncio.wait_for(
            private.decide(bearer=admission.bearer, body=wire),
            timeout=_DECISION_TIMEOUT_SECONDS,
        )
    except Exception:
        return admission_error("MCP_AUTHORIZATION_UNAVAILABLE", 503)
    if not isinstance(decision, PrivateAdmissionReply):
        return admission_error("MCP_AUTHORIZATION_UNAVAILABLE", 503)
    if decision.status_code == 401:
        return admission_error("MCP_IDENTITY_UNVERIFIED", 401)
    if decision.status_code == 403:
        return admission_error("MCP_ACCESS_DENIED", 403)
    if (
        decision.status_code != 200
        or not isinstance(decision.body, bytes)
        or not _strict_permit_response(decision.body)
    ):
        return admission_error("MCP_AUTHORIZATION_UNAVAILABLE", 503)
    return None
