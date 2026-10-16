"""Local signed fixture: a private Web browser tool never owns a global browser."""

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
from hand_runtime import PrivateDecisionReply, ResolvedEffect, ResourceTrust
from starlette.types import ASGIApp, Message, Scope
from web_hand._mcp_browser_activation import (
    BrowserSnapshot,
    BrowserSnapshotRequest,
    TrustedWebBrowserPorts,
    _public_snapshot,
    build_protected_web_browser_app,
)

_ISSUER = "https://briareus.koba-nexus.ru/auth/v1/"
_AUDIENCE = "https://briareus.koba-nexus.ru/hands/web/mcp"
_PROJECT = b"12345678-1234-4234-8234-123456789abc"
_SESSION = b"12345678-1234-4234-8234-123456789abd"


class UnavailableWebOwner:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.synthetic_permit = False
        self.provide_snapshot = False
        self.validated = False

    async def resolve(self, _args: dict) -> ResolvedEffect:
        self.calls.append("resolve")
        if not self.synthetic_permit:
            raise ValueError("trusted Project browser owner unavailable")
        return ResolvedEffect(
            "web.access",
            "browser_session",
            "owner-session-1",
            {"browser_handle": "owner-session-1", "max_text_chars": 128},
        )

    async def decide(self, **_kwargs: object) -> PrivateDecisionReply:
        self.calls.append("decision")
        if not self.synthetic_permit:
            raise AssertionError("private PDP must not be contacted")
        # A fixture JSON Allow is deliberately NOT independent Cedar proof.
        return PrivateDecisionReply(200, b'{"allowed":true}')

    async def validate_current(self, _request: object) -> None:
        self.calls.append("revalidate")
        self.validated = True
        raise RuntimeError("independent browser owner final lease unavailable")

    async def read_snapshot(self, request: object) -> BrowserSnapshot:
        self.calls.append("snapshot")
        assert isinstance(request, BrowserSnapshotRequest)
        assert request.browser_handle == "owner-session-1"
        assert request.project_id == UUID(_PROJECT.decode())
        assert request.agent_session_id == UUID(_SESSION.decode())
        assert request.grant_revision == 1
        assert request.max_text_chars == 128
        if self.provide_snapshot:
            return BrowserSnapshot("https://example.org", "Fixture", "owner-provided text")
        raise RuntimeError("no verified Project-scoped browser worker")


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
        (b"host", b"briareus-web:8000"),
        (b"content-type", b"application/json"),
        (b"accept", b"application/json, text/event-stream"),
        (b"x-briareus-project-uuid", _PROJECT),
        (b"x-briareus-agent-session-uuid", _SESSION),
        (b"x-briareus-grant-revision", b"1"),
    ]
    if bearer is not None:
        headers.append((b"authorization", f"Bearer {bearer}".encode("ascii")))
    is_call = method == "POST"
    path = "/mcp" if is_call else "/health/ready"
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "server": ("briareus-web", 8000),
        "client": ("127.0.0.1", 10000),
    }
    await asyncio.wait_for(app(scope, receive, send), 8)
    status = next(event["status"] for event in sent if event["type"] == "http.response.start")
    payload = b"".join(
        event.get("body", b"") for event in sent if event["type"] == "http.response.body"
    )
    return status, json.loads(payload) if payload else {}


async def main() -> None:
    from web_hand.server import app as deployed_default

    status, ready = await exchange(deployed_default, method="GET")
    assert status == 503 and ready["authorization"] == "not_configured"
    owner = UnavailableWebOwner()
    ports = TrustedWebBrowserPorts(owner.resolve, owner, owner)
    try:
        TrustedWebBrowserPorts(owner.resolve, owner, object())
    except ValueError:
        pass
    else:
        raise AssertionError("partial browser worker accepted")
    for missing in (None, object()):
        try:
            build_protected_web_browser_app(missing)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError("missing trusted Web ports accepted")

    with patch.dict(
        os.environ, {"MCP_RESOURCE_AUDIENCE": "", "MCP_RESOURCE_SIGNING_ALGORITHM": ""}
    ):
        try:
            build_protected_web_browser_app(ports)
        except ValueError:
            pass
        else:
            raise AssertionError("unsigned Web activation accepted")

    # Pure output contract: no raw URLs, HTML, cookies or CDP are allowed.
    assert _public_snapshot(BrowserSnapshot("https://example.org", "Title", "hello"), 20) == {
        "origin": "https://example.org",
        "title": "Title",
        "visible_text": "hello",
    }
    for bad in (
        BrowserSnapshot("https://user:password@example.org", "Title", "hello"),
        BrowserSnapshot("https://example.org/private?token=test", "Title", "hello"),
        BrowserSnapshot("http://example.org", "Title", "hello"),
        BrowserSnapshot("https://example.org", "Title", "text over 3 chars"),
    ):
        try:
            _public_snapshot(bad, 3)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe snapshot payload accepted")

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
        claims | {"aud": "https://briareus.koba-nexus.ru/hands/files/mcp"}, key, algorithm="RS256"
    )
    with (
        patch.object(ResourceTrust, "verifier", return_value=verifier),
        patch.dict(
            os.environ,
            {"MCP_RESOURCE_AUDIENCE": _AUDIENCE, "MCP_RESOURCE_SIGNING_ALGORITHM": "RS256"},
        ),
    ):
        app = build_protected_web_browser_app(ports)

    async with app.router.lifespan_context(app):
        status, pending = await exchange(app, method="GET")
        assert status == 503 and pending["authorization"] == "owner_ports_injected_unaccepted"
        listing = b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
        status, _ = await exchange(app, method="POST", body=listing)
        assert status == 401 and not owner.calls
        status, _ = await exchange(app, method="POST", body=listing, bearer="unsigned")
        assert status == 401 and not owner.calls
        status, _ = await exchange(app, method="POST", body=listing, bearer=wrong_audience)
        assert status == 401 and not owner.calls
        status, reply = await exchange(app, method="POST", body=listing, bearer=token)
        assert status == 200 and "result" in reply, reply
        names = {item["name"] for item in reply["result"]["tools"]}
        assert names == {
            "browser_snapshot",
            "hand_permission_probe",
            "hand_status",
            "hand_source_summary",
        }, names
        assert "browser_click" not in names and "browser_open" not in names
        call = (
            b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":'
            b'{"name":"browser_snapshot","arguments":'
            b'{"browser_handle":"untrusted","max_text_chars":128}}}'
        )
        status, failure = await exchange(app, method="POST", body=call, bearer=token)
        assert status == 200 and failure["result"]["isError"]
        assert owner.calls == ["resolve"], owner.calls

        owner.calls.clear()
        owner.synthetic_permit = True
        status, failure = await exchange(app, method="POST", body=call, bearer=token)
        assert status == 200 and failure["result"]["isError"], (status, failure)
        assert owner.calls == ["resolve", "decision", "snapshot"], owner.calls
        owner.calls.clear()
        owner.provide_snapshot = True
        status, failure = await exchange(app, method="POST", body=call, bearer=token)
        assert status == 200 and failure["result"]["isError"]
        assert owner.calls == ["resolve", "decision", "snapshot", "revalidate"]
        assert owner.validated is True
        assert "owner-provided text" not in str(failure)

    print("WEB_BROWSER_OPTIONAL_SIGNED_FIXTURE_PASS")
    print("WEB_AFTER_READ_REVOKED_OWNER_LEASE_DENIES_BEFORE_RESPONSE")
    print("FAKE_ALLOW_CANNOT_READ_WITHOUT_VERIFIED_PROJECT_BROWSER_WORKER")
    print("WEB_DEFAULT_SERVER_STILL_DIAGNOSTIC_ONLY")
    print("NO_LIVE_USER_CEDAR_PERMISSION_OR_BROWSER_EFFECT")


if __name__ == "__main__":
    asyncio.run(main())
