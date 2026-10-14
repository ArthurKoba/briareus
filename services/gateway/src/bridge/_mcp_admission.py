"""Coarse MCP connection admission against independent Authorization.

Incoming selectors are not identity proof. Only an independently attested
Authorization 200 with the exact Permit body may allow Gateway forwarding.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

from .single_origin import MCP_MODULES

_AUTHORIZATION_DECIDE = "http://briareus-authorization:8000/internal/v1/authorization/decide"
_HAND_TARGETS = {name: f"http://briareus-{name}:8000/mcp" for name in MCP_MODULES}
_DECISION_TIMEOUT = httpx.Timeout(connect=3, read=5, write=5, pool=3)


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
    if len(values) != 1 or not values[0].strip() or len(values[0]) > 128:
        raise McpAdmissionRejected("MCP_CONTEXT_INVALID", 400)
    return values[0].strip()


def parse_connection_admission(request: Request) -> ConnectionAdmission:
    """Parse strictly bounded, *untrusted* selectors for the real PDP."""
    hand = request.url.path.removeprefix("/hands/").removesuffix("/mcp")
    if hand not in _HAND_TARGETS or request.url.path != f"/hands/{hand}/mcp":
        raise McpAdmissionRejected("MCP_MODULE_UNKNOWN", 404)
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
        project_uuid = UUID(_single_header(request, "x-briareus-project-uuid"))
        agent_session_uuid = UUID(_single_header(request, "x-briareus-agent-session-uuid"))
        raw_revision = _single_header(request, "x-briareus-grant-revision")
        if not raw_revision.isascii() or not raw_revision.isdecimal():
            raise ValueError("non-decimal grant revision")
        revision = int(raw_revision)
    except (ValueError, OverflowError) as exc:
        raise McpAdmissionRejected("MCP_CONTEXT_INVALID", 400) from exc
    if (
        project_uuid.version != 4
        or agent_session_uuid.version != 4
        or not 1 <= revision <= 2**63 - 1
    ):
        raise McpAdmissionRejected("MCP_CONTEXT_INVALID", 400)
    return ConnectionAdmission(hand, bearer, project_uuid, agent_session_uuid, revision)


async def authorize_connection(
    client: httpx.AsyncClient, admission: ConnectionAdmission
) -> JSONResponse | None:
    """Consult real independent Authorization; unavailable/unknown means deny."""
    try:
        decision = await client.post(
            _AUTHORIZATION_DECIDE,
            json=admission.command(),
            headers={"Authorization": admission.bearer, "Accept": "application/json"},
            timeout=_DECISION_TIMEOUT,
        )
    except (httpx.HTTPError, TimeoutError):
        return admission_error("MCP_AUTHORIZATION_UNAVAILABLE", 503)
    if decision.status_code == 401:
        return admission_error("MCP_IDENTITY_UNVERIFIED", 401)
    if decision.status_code == 403:
        return admission_error("MCP_ACCESS_DENIED", 403)
    if decision.status_code != 200:
        return admission_error("MCP_AUTHORIZATION_UNAVAILABLE", 503)
    try:
        permit = decision.json()
    except ValueError:
        return admission_error("MCP_AUTHORIZATION_UNAVAILABLE", 503)
    if permit != {"allowed": True}:
        return admission_error("MCP_AUTHORIZATION_UNAVAILABLE", 503)
    return None
