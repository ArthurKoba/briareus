"""Cross-Hand optional metadata stage: signed fixture and owner-deny protocol.

All four new read-only tools remain OFF in normal deployed Hand servers.
This test has no actual Project owner, Cedar grant, filesystem or network IO.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from unittest.mock import patch

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp.server.auth.providers.jwt import JWTVerifier
from hand_runtime import (
    PrivateDecisionReply,
    ResolvedEffect,
    ResourceMetadata,
    ResourceTrust,
    TrustedMetadataPorts,
)
from hand_runtime._owner_metadata import _sanitize_owner_metadata
from infrastructure_hand._mcp_metadata_activation import build_protected_infrastructure_metadata_app
from reverse_hand._mcp_metadata_activation import build_protected_reverse_metadata_app
from starlette.applications import Starlette
from svc_hand._mcp_metadata_activation import build_protected_svc_metadata_app
from terminal_hand._mcp_metadata_activation import build_protected_terminal_metadata_app

_ISSUER = "https://briareus.koba-nexus.ru/auth/v1/"
_PROJECT = "12345678-1234-4234-8234-123456789abc"
_SESSION = "12345678-1234-4234-8234-123456789abd"
_CASES = (
    (
        "terminal",
        "workspace_metadata",
        "terminal.execute",
        "workspace",
        build_protected_terminal_metadata_app,
    ),
    (
        "svc",
        "repository_metadata",
        "integrations.use",
        "repository",
        build_protected_svc_metadata_app,
    ),
    (
        "infrastructure",
        "application_metadata",
        "integrations.use",
        "application",
        build_protected_infrastructure_metadata_app,
    ),
    (
        "reverse",
        "analysis_project_metadata",
        "analysis.import",
        "analysis_project",
        build_protected_reverse_metadata_app,
    ),
)


class InertOwner:
    def __init__(self, *, action: str, kind: str) -> None:
        self.action, self.kind = action, kind
        self.calls: list[str] = []
        self.fake_cedar = False
        self.allow_bounded_fixture = False
        self.rebind_grant = False

    async def resolve(self, raw: dict) -> ResolvedEffect:
        self.calls.append("resolve")
        if not self.fake_cedar:
            raise ValueError("no genuine Project owner")
        assert raw["resource_handle"] == "caller-handle"
        # The real owner, not the MCP argument, must produce the canonical
        # executable resource handle and validate the current Project lease.
        return ResolvedEffect(
            self.action, self.kind, "owner-resource", {"resource_handle": "owner-resource"}
        )

    async def decide(self, **_arguments: object) -> PrivateDecisionReply:
        self.calls.append("private-decision")
        assert self.fake_cedar
        return PrivateDecisionReply(200, b'{"allowed":true}')

    async def inspect(self, request: object) -> ResourceMetadata:
        self.calls.append("inspect")
        assert request.resource_handle == "owner-resource"
        assert request.action == self.action and request.resource_kind == self.kind
        assert str(request.project_uuid) == _PROJECT
        assert str(request.agent_session_uuid) == _SESSION
        assert request.grant_revision == 1
        assert request.bearer.startswith("Bearer ")
        if self.allow_bounded_fixture:
            if self.rebind_grant:
                # Simulate an internal request-context swap during owner I/O.
                # It must not turn the earlier Cedar Permit into a response.
                from fastmcp.server.dependencies import get_http_request

                http = get_http_request()
                http.scope["headers"] = [
                    (key, b"2" if key == b"x-briareus-grant-revision" else value)
                    for key, value in http.scope["headers"]
                ]
            return ResourceMetadata("degraded", 11)
        raise ValueError("no independent signed owner inspector")


async def exercise(
    hand: str,
    tool: str,
    action: str,
    kind: str,
    factory: Callable[[TrustedMetadataPorts], Starlette],
) -> None:
    owner = InertOwner(action=action, kind=kind)
    ports = TrustedMetadataPorts(owner.resolve, owner, owner)
    try:
        TrustedMetadataPorts(owner.resolve, owner, object())
    except ValueError:
        pass
    else:
        raise AssertionError("missing trusted inspector permitted")
    with patch.dict(
        os.environ, {"MCP_RESOURCE_AUDIENCE": "", "MCP_RESOURCE_SIGNING_ALGORITHM": ""}
    ):
        try:
            factory(ports)
        except ValueError:
            pass
        else:
            raise AssertionError("metadata tool installed without resource signer")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    audience = f"https://briareus.koba-nexus.ru/hands/{hand}/mcp"
    verifier = JWTVerifier(public_key=public, issuer=_ISSUER, audience=audience, algorithm="RS256")
    now = int(time.time())
    claims = {
        "iss": _ISSUER,
        "aud": audience,
        "sub": "fixture-user",
        "iat": now,
        "nbf": now,
        "exp": now + 60,
        "azp": "fixture-client",
        "jti": "fixture-id",
        "typ": "Bearer",
    }
    token = jwt.encode(claims, key, algorithm="RS256")
    alien = jwt.encode(
        claims | {"aud": "https://briareus.koba-nexus.ru/hands/files/mcp"}, key, algorithm="RS256"
    )
    with (
        patch.object(ResourceTrust, "verifier", return_value=verifier),
        patch.dict(
            os.environ,
            {"MCP_RESOURCE_AUDIENCE": audience, "MCP_RESOURCE_SIGNING_ALGORITHM": "RS256"},
        ),
    ):
        app = factory(ports)
    headers = {
        "host": f"briareus-{hand}:8000",
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "x-briareus-project-uuid": _PROJECT,
        "x-briareus-agent-session-uuid": _SESSION,
        "x-briareus-grant-revision": "1",
    }
    listing = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool, "arguments": {"resource_handle": "caller-handle"}},
    }
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=f"http://briareus-{hand}:8000",
            trust_env=False,
            timeout=6,
        ) as client,
    ):
        readiness = await client.get("/health/ready", headers=headers)
        assert readiness.status_code == 503
        assert readiness.json()["authorization"] == "owner_ports_injected_unaccepted"
        no_auth = await client.post("/mcp", json=listing, headers=headers)
        assert no_auth.status_code == 401 and not owner.calls
        wrong_aud = await client.post(
            "/mcp", json=listing, headers=headers | {"authorization": "Bearer " + alien}
        )
        assert wrong_aud.status_code == 401 and not owner.calls
        signed = headers | {"authorization": "Bearer " + token}
        available = await client.post("/mcp", json=listing, headers=signed)
        assert available.status_code == 200, available.text
        names = {t["name"] for t in available.json()["result"]["tools"]}
        assert names == {tool, "hand_status", "hand_source_summary", "hand_permission_probe"}, (
            hand,
            names,
        )
        denied = await client.post("/mcp", json=call, headers=signed)
        assert denied.status_code == 200 and denied.json()["result"]["isError"]
        assert owner.calls == ["resolve"], owner.calls
        owner.calls.clear()
        owner.fake_cedar = True
        second = await client.post("/mcp", json=call, headers=signed)
        assert second.status_code == 200 and second.json()["result"]["isError"]
        assert owner.calls == ["resolve", "private-decision", "inspect"], owner.calls
        owner.calls.clear()
        owner.allow_bounded_fixture = True
        good = await client.post("/mcp", json=call, headers=signed)
        assert good.status_code == 200 and good.json()["result"]["isError"] is False
        assert good.json()["result"]["structuredContent"] == {
            "state": "degraded",
            "revision": 11,
        }, good.json()
        owner.calls.clear()
        owner.rebind_grant = True
        rebinding = await client.post("/mcp", json=call, headers=signed)
        assert rebinding.status_code == 200
        assert rebinding.json()["result"]["isError"]
        assert owner.calls == ["resolve", "private-decision", "inspect"], owner.calls
    print(f"READONLY_{hand.upper()}_SIGNED_FIXTURE_NO_REAL_OWNER_OR_CEDAR")


async def main() -> None:
    for item in (
        ResourceMetadata("active", 0),
        ResourceMetadata("unknown", True),
        ResourceMetadata("unknown", 2**63),
        ResourceMetadata("secrets", 1),
    ):
        try:
            _sanitize_owner_metadata(item)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe generic owner metadata accepted")
    for case in _CASES:
        await exercise(*case)
    print("FOUR_UNMOUNTED_STATUS_TOOLS_PASS_WITH_INDEPENDENT_AUTH_BOUNDARIES")


if __name__ == "__main__":
    asyncio.run(main())
