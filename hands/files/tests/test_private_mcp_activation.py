"""Native signed-fixture preflight for an optional, unmounted Files tool.

All actual private owner calls deny. The signed fixture is local ephemeral RSA,
not a real Rauthy User or Cedar Permit.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from unittest.mock import patch
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp.server.auth.providers.jwt import JWTVerifier
from files_hand._mcp_activation import TrustedFilesReadPorts, build_protected_files_app
from files_hand._read_adapter import FilesReadArguments
from files_hand._read_scope import FilesReadSelector
from hand_runtime import PrivateDecisionReply, ResolvedEffect, ResourceTrust
from starlette.types import ASGIApp, Message, Scope

_ISSUER = "https://briareus.koba-nexus.ru/auth/v1/"
_AUDIENCE = "https://briareus.koba-nexus.ru/hands/files/mcp"
_PROJECT = b"12345678-1234-4234-8234-123456789abc"
_SESSION = b"12345678-1234-4234-8234-123456789abd"


class UnavailableOwner:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fixture_permit = False

    async def resolve(self, _args: dict) -> object:
        self.calls.append("resolve")
        if self.fixture_permit:
            arguments = FilesReadArguments("sample.txt", 128)
            resource_id = FilesReadSelector(UUID(_PROJECT.decode()), arguments).resource_id
            return ResolvedEffect(
                "files.read", "workspace_path", resource_id, arguments.canonical_arguments()
            )
        raise ValueError("fixture owner is not configured")

    async def decide(self, **_kwargs: object) -> object:
        self.calls.append("decision")
        if self.fixture_permit:
            # A controlled transport fixture is NOT a Cedar authorization.
            return PrivateDecisionReply(200, b'{"allowed":true}')
        raise AssertionError("no trusted private Authorization peer")

    def open_channel(self, _request: object) -> object:
        self.calls.append("channel")
        raise ValueError("no trusted Rauthy Files channel")

    def hold_root(self, **_kwargs: object) -> object:
        self.calls.append("root")
        raise AssertionError("no current Files root mapping")


async def exchange(
    app: ASGIApp, *, method: str, body: bytes = b"", bearer: str | None = None
) -> tuple[int, dict[str, object]]:
    sent: list[Message] = []
    supplied = False
    disconnected = asyncio.Event()

    async def receive() -> Message:
        nonlocal supplied
        if not supplied:
            supplied = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    headers = [
        (b"host", b"briareus-files:8000"),
        (b"content-type", b"application/json"),
        (b"accept", b"application/json, text/event-stream"),
        (b"x-briareus-project-uuid", _PROJECT),
        (b"x-briareus-agent-session-uuid", _SESSION),
        (b"x-briareus-grant-revision", b"1"),
    ]
    if bearer is not None:
        headers.append((b"authorization", f"Bearer {bearer}".encode("ascii")))
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/mcp" if method == "POST" else "/health/ready",
        "raw_path": b"/mcp" if method == "POST" else b"/health/ready",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "server": ("briareus-files", 8000),
        "client": ("127.0.0.1", 10000),
    }
    await asyncio.wait_for(app(scope, receive, send), 8)
    status = next(event["status"] for event in sent if event["type"] == "http.response.start")
    payload = b"".join(
        event.get("body", b"") for event in sent if event["type"] == "http.response.body"
    )
    return status, json.loads(payload) if payload else {}


async def main() -> None:
    owner = UnavailableOwner()
    ports = TrustedFilesReadPorts(owner.resolve, owner, owner, owner)
    try:
        TrustedFilesReadPorts(owner.resolve, owner, owner, object())
    except ValueError:
        pass
    else:
        raise AssertionError("partial Files root port graph accepted")
    for absence in (None, object()):
        try:
            build_protected_files_app(absence)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError("missing trusted owner ports accepted")

    with patch.dict(
        os.environ, {"MCP_RESOURCE_AUDIENCE": "", "MCP_RESOURCE_SIGNING_ALGORITHM": ""}
    ):
        try:
            build_protected_files_app(ports)
        except ValueError:
            pass
        else:
            raise AssertionError("unsigned Files activation accepted")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    verifier = JWTVerifier(public_key=public, issuer=_ISSUER, audience=_AUDIENCE, algorithm="RS256")
    now = int(time.time())
    claims = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": "local-signed-fixture",
        "iat": now,
        "nbf": now,
        "exp": now + 60,
        "azp": "local-client",
        "jti": "local-token",
        "typ": "Bearer",
    }
    token = jwt.encode(claims, key, algorithm="RS256")
    wrong_audience = jwt.encode(
        claims | {"aud": "https://briareus.koba-nexus.ru/hands/web/mcp"},
        key,
        algorithm="RS256",
    )
    wrong_purpose = jwt.encode(claims | {"typ": "Refresh"}, key, algorithm="RS256")
    with (
        patch.object(ResourceTrust, "verifier", return_value=verifier),
        patch.dict(
            os.environ,
            {"MCP_RESOURCE_AUDIENCE": _AUDIENCE, "MCP_RESOURCE_SIGNING_ALGORITHM": "RS256"},
        ),
    ):
        app = build_protected_files_app(ports)
    async with app.router.lifespan_context(app):
        status, pending = await exchange(app, method="GET")
        assert status == 503 and pending["authorization"] == "owner_ports_injected_unaccepted"
        body = b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
        status, _ = await exchange(app, method="POST", body=body)
        assert status == 401 and not owner.calls
        status, _ = await exchange(app, method="POST", body=body, bearer="unsigned")
        assert status == 401 and not owner.calls
        status, _ = await exchange(app, method="POST", body=body, bearer=wrong_audience)
        assert status == 401 and not owner.calls
        status, reply = await exchange(app, method="POST", body=body, bearer=token)
        assert status == 200 and "result" in reply, reply
        names = {item["name"] for item in reply["result"]["tools"]}
        assert names == {
            "read_file",
            "hand_permission_probe",
            "hand_status",
            "hand_source_summary",
        }, names
        body = (
            b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":'
            b'{"name":"read_file","arguments":{"path":"sample.txt","max_bytes":128}}}'
        )
        status, result = await exchange(app, method="POST", body=body, bearer=wrong_purpose)
        assert (status == 401 or result.get("result", {}).get("isError")) and not owner.calls
        status, result = await exchange(app, method="POST", body=body, bearer=token)
        assert status == 200 and result["result"]["isError"], (status, result)
        assert owner.calls == ["resolve"], owner.calls
        # Synthetic positive Cedar JSON is deliberately insufficient:
        # without a separately verified signed Files channel, no native
        # owner root or data access may begin, even after a false Permit.
        owner.calls.clear()
        owner.fixture_permit = True
        status, result = await exchange(app, method="POST", body=body, bearer=token)
        assert status == 200 and result["result"]["isError"], (status, result)
    assert owner.calls == ["resolve", "decision", "channel"], owner.calls
    print("SIGNED_FIXTURE_FILES_TOOL_REGISTERED_ONLY_WITH_ALL_TRUSTED_PORTS")
    print("FAKE_CEDAR_ALLOW_STILL_DENIED_BY_MISSING_TRUSTED_READ_CHANNEL")
    print("SIGNED_FIXTURE_CANNOT_READ_WITHOUT_CURRENT_OWNER_AND_CEDAR")
    print("NO_ACTUAL_RAUTHY_USER_OR_FILES_PERMIT")


if __name__ == "__main__":
    asyncio.run(main())
