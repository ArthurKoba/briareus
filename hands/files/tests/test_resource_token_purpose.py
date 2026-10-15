"""Real SDK signature checks with ephemeral tokens; no deployed identity/grant."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import JWTVerifier
from hand_runtime import _resource_claims
from hand_runtime._effect_auth import (
    EffectAuthorizationMiddleware,
    PrivateDecisionReply,
    ResolvedEffect,
    ToolEffectBinding,
)
from hand_runtime._resource_claims import valid_resource_claims
from mcp_types import CallToolRequestParams
from starlette.requests import Request


async def main() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    issuer = "https://briareus.koba-nexus.ru/auth/v1/"
    audience = "https://briareus.koba-nexus.ru/hands/files/mcp"
    verifier = JWTVerifier(public_key=public, issuer=issuer, audience=audience, algorithm="RS256")
    now = int(time.time())
    base = {
        "iss": issuer,
        "aud": ["fixture-client", audience],
        "sub": "fixture-subject",
        "iat": now,
        "nbf": now,
        "exp": now + 60,
        "azp": "fixture-client",
        "jti": "fixture-token-id",
        "typ": "Bearer",
    }
    visits = []

    async def resolver(arguments: dict) -> object:
        visits.append(arguments)
        raise ValueError("no actual resource owner configured")

    async def effect(_context: object) -> object:
        raise AssertionError("no business effect authorized in this test")

    middleware = EffectAuthorizationMiddleware(
        "files",
        effect_bindings={"read_file": ToolEffectBinding("files.read", "workspace_path", resolver)},
        private_decision=object(),
    )
    for update in (
        {},
        {"typ": "Id"},
        {"typ": "Refresh"},
        {"typ": None},
        {"cnf": {"jkt": "unsupported"}},
        {"act": {"sub": "delegated-untrusted"}},
        {"exp": now + 86401},
        {"jti": "contains space"},
        {"azp": ""},
        {"aud": [audience, audience]},
    ):
        claims = base | update
        token = jwt.encode(claims, key, algorithm="RS256")
        verified = await verifier.verify_token(token)
        if verified is None:
            assert update  # SDK may itself reject some malformed inputs.
            continue
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/mcp",
                "headers": [(b"authorization", ("Bearer " + token).encode())],
            }
        )
        before = len(visits)
        context = SimpleNamespace(
            message=CallToolRequestParams(name="read_file", arguments={"path": "file"})
        )
        with (
            patch("hand_runtime._effect_auth.get_access_token", return_value=verified),
            patch("hand_runtime._effect_auth.get_http_request", return_value=request),
        ):
            try:
                await middleware.on_call_tool(context, effect)
            except ToolError as exc:
                expected = "MCP_IDENTITY_UNVERIFIED" if update else "MCP_RESOURCE_SCOPE_UNAVAILABLE"
                assert str(exc) == expected, (update.keys(), str(exc))
            else:
                raise AssertionError("effect executed without actual authority")
        assert len(visits) == before + (0 if update else 1)

    # A synthetic positive reply is used only to exercise the waiting
    # boundary. It is never sent to a running Hand or used to read a file.
    class Context(SimpleNamespace):
        def copy(self, **updates: object) -> Context:
            return Context(**(vars(self) | updates))

    async def scoped_resolver(_arguments: dict) -> ResolvedEffect:
        return ResolvedEffect("files.read", "workspace_path", "fixture-file", {"path": "file"})

    async def decision_case(mode: str) -> None:
        raw = jwt.encode(base, key, algorithm="RS256")
        original = await verifier.verify_token(raw)
        alternate_raw = jwt.encode(base | {"sub": "other-fixture-subject"}, key, algorithm="RS256")
        alternate = await verifier.verify_token(alternate_raw)
        active = [original, raw]
        clock = [float(now)]
        calls: list[str] = []

        class PendingDecision:
            async def decide(self, **_arguments: object) -> PrivateDecisionReply:
                if mode == "expired_during_reply":
                    clock[0] = now + 61
                elif mode == "rebound_during_reply":
                    active[:] = [alternate, alternate_raw]
                return PrivateDecisionReply(200, b'{"allowed":true}')

        async def fixture_only_effect(_context: object) -> str:
            calls.append("fixture_only_no_file_access")
            return "fixture"

        def current_request() -> Request:
            return Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/mcp",
                    "headers": [
                        (b"authorization", ("Bearer " + active[1]).encode()),
                        (b"x-briareus-project-uuid", b"11111111-1111-4111-8111-111111111111"),
                        (b"x-briareus-agent-session-uuid", b"22222222-2222-4222-8222-222222222222"),
                        (b"x-briareus-grant-revision", b"1"),
                    ],
                }
            )

        gate = EffectAuthorizationMiddleware(
            "files",
            effect_bindings={
                "read_file": ToolEffectBinding("files.read", "workspace_path", scoped_resolver)
            },
            private_decision=PendingDecision(),
        )
        with (
            patch.object(_resource_claims, "time", SimpleNamespace(time=lambda: clock[0])),
            patch("hand_runtime._effect_auth.get_access_token", side_effect=lambda: active[0]),
            patch("hand_runtime._effect_auth.get_http_request", side_effect=current_request),
        ):
            try:
                result = await gate.on_call_tool(
                    Context(
                        message=CallToolRequestParams(name="read_file", arguments={"path": "file"})
                    ),
                    fixture_only_effect,
                )
            except ToolError as exc:
                assert mode != "unchanged" and str(exc) == "MCP_IDENTITY_UNVERIFIED"
            else:
                assert mode == "unchanged" and result == "fixture"
        assert len(calls) == (1 if mode == "unchanged" else 0)

    for mode in ("unchanged", "expired_during_reply", "rebound_during_reply"):
        await decision_case(mode)
    print("TOKEN_EXPIRY_OR_REBIND_DURING_PDP_REPLY_DENIES_BEFORE_EFFECT_PASS")
    for field in ("exp", "iat", "nbf"):
        for value in (True, "123", None, float(now)):
            assert not valid_resource_claims(base | {field: value})
    assert not valid_resource_claims(base | {"iat": now + 100})
    assert not valid_resource_claims(base | {"nbf": now + 100})
    assert not valid_resource_claims(base | {"exp": now - 1})
    assert not valid_resource_claims(base | {"exp": now + 86401})
    assert not valid_resource_claims(base | {"act": {"sub": "delegated"}})
    print("SDK_SIGNED_FIXTURE_ID_REFRESH_ACT_DELEGATION_LONG_LIFETIME_DENIED_PASS")
    print("VALID_BEARER_STILL_REQUIRES_INDEPENDENT_OWNER_AND_CEDAR_NO_PUBLIC_GRANT")


asyncio.run(main())
