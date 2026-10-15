"""Native Control Panel login transport boundary, not an auth provider.

The browser's *future* native credential/MFA endpoints stay with the
independently authenticated Control Panel API. Gateway cannot impersonate
that API, issue a login result, or serve hosted Rauthy SvelteKit UI.
MCP private Decision remains unconfigured/closed in this source test.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx

from bridge.thin_gateway import build_app

_ORIGIN = "https://briareus.koba-nexus.ru"


class _Bytes(httpx.AsyncByteStream):
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.payload

    async def aclose(self) -> None:
        pass


async def _run() -> None:
    forwarded: list[httpx.Request] = []

    def response_from_owner(req: httpx.Request) -> httpx.Response:
        forwarded.append(req)
        if req.url.host == "briareus-control-panel-api" and req.url.path == ("/api/v1/auth/start"):
            # Actual Backend owns this 201 Init stage, illustrated here by
            # protocol-shaped transport bytes only, not a fabricated User.
            return httpx.Response(
                201,
                headers=[
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                    (
                        b"set-cookie",
                        b"__Host-briareus_native_transaction=opaque_fixture;"
                        b" HttpOnly; Secure; Path=/; SameSite=Lax",
                    ),
                ],
                stream=_Bytes(
                    b'{"stage":"first_factor_required","authenticated":false,"expires_in":300}'
                ),
            )
        if req.url.host == "briareus-control-panel-api" and req.url.path == ("/api/v1/auth/pow"):
            return httpx.Response(
                200,
                headers=[
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                ],
                stream=_Bytes(
                    b'{"challenge":"synthetic_fixture_not_a_real_pow","authenticated":false}'
                ),
            )
        if req.url.host == "briareus-control-panel-api" and req.url.path == (
            "/api/v1/auth/capabilities"
        ):
            return httpx.Response(
                200,
                headers={"content-type": "application/json", "cache-control": "no-store"},
                stream=_Bytes(
                    b'{"protocol":"rauthy-native-v1","first_factor":"password",'
                    b'"pow":"client-solved","cancel":true,"continuations":[]}'
                ),
            )
        if req.url.host == "briareus-control-panel-api" and req.url.path == ("/api/v1/auth/cancel"):
            return httpx.Response(
                204,
                headers=[
                    (b"cache-control", b"no-store"),
                    (
                        b"set-cookie",
                        b"__Host-briareus_native_transaction=;"
                        b" HttpOnly; Secure; Path=/; SameSite=Lax; Max-Age=0",
                    ),
                ],
                stream=_Bytes(b""),
            )
        if req.url.host == "briareus-control-panel-api" and req.url.path == (
            "/api/v1/auth/first-factor"
        ):
            # Only unconfigured/unsupported negative transport; never
            # synthesize a password-verified or signed-in owner identity.
            return httpx.Response(
                409,
                headers={"content-type": "application/json", "cache-control": "no-store"},
                stream=_Bytes(
                    b'{"stage":"otp_pending","authenticated":false,'
                    b'"continuation_available":false,"restart_required":true}'
                ),
            )
        if req.url.host == "briareus-control-panel-api" and req.url.path == (
            "/api/v1/auth/_fixture/response"
        ):
            # Stub ONLY: exercising HTTP Set-Cookie fidelity during a future
            # native BFF challenge, not creating a real provider session.
            return httpx.Response(
                202,
                headers=[
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                    (b"set-cookie", b"fixture_a=opaque; HttpOnly; Secure; Path=/; SameSite=Lax"),
                    (b"set-cookie", b"fixture_b=opaque; HttpOnly; Secure; Path=/; SameSite=Lax"),
                ],
                stream=_Bytes(b'{"state":"challenge_pending"}'),
            )
        if req.url.host == "briareus-control-panel-api" and req.url.path == (
            "/api/v1/auth/_fixture/redirect"
        ):
            return httpx.Response(
                303,
                headers=[
                    (b"location", b"https://briareus.koba-nexus.ru/panel/"),
                    (b"set-cookie", b"fixture_a=; HttpOnly; Secure; Path=/; Max-Age=0"),
                    (b"cache-control", b"no-store"),
                ],
                stream=_Bytes(b""),
            )
        if req.url.host == "briareus-control-panel-api":
            # This is a STUB for exact Gateway routing only. No Backend native
            # password/MFA BFF has been accepted in the product at this stage.
            return httpx.Response(
                503,
                headers={"content-type": "application/json", "cache-control": "no-store"},
                stream=_Bytes(b'{"detail":"native_login_source_not_enabled"}'),
            )
        if req.url.host == "briareus-rauthy":
            # Genuine transport boundary, no real hosted login or tokens.
            if req.url.path != "/auth/v1/health":
                raise AssertionError("unexpected provider route")
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_Bytes(b'{"healthy":true}'),
            )
        if req.url.host == "briareus-control-panel-ui":
            if req.url.path != "/panel/":
                raise AssertionError("UI owner received an unexpected path")
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                stream=_Bytes(b'<div id="app">Native Control Panel</div><!-- noindex -->'),
            )
        raise AssertionError("unwanted provider request during native Panel transport")

    app = build_app()
    handler = next(
        route.endpoint.__self__
        for route in app.routes
        if getattr(route, "path", None) == "/api/{path:path}"
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(response_from_owner)) as upstream,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=_ORIGIN) as browser,
    ):
        handler._client = upstream

        panel = await browser.get("/panel/")
        assert panel.status_code == 200
        assert b"Native Control Panel" in panel.content
        assert len(forwarded) == 1 and forwarded[0].url.host == "briareus-control-panel-ui"

        # Removing obsolete hosted-login SvelteKit routes must be a real
        # physical reduction of the public attack surface, not a UI claim.
        for path in (
            "/_app/immutable/entry/start.DU3Iye__.js",
            "/assets/rauthy_light.svg",
            "/_app/immutable/chunks/version.js",
            "/assets/unrelated.png",
        ):
            before = len(forwarded)
            answer = await browser.get(path)
            assert answer.status_code == 404, (path, answer.status_code)
            assert len(forwarded) == before, ("provider asset reached owner", path)

        # The provider sees ONLY Gateway-issued canonical Host/Proto claims,
        # even if a hostile browser supplied unrelated forwarded assertions.
        provider_before = len(forwarded)
        health = await browser.get(
            "/auth/v1/health",
            headers={
                "X-Forwarded-User": "browser_claim_must_not_pass",
                "X-Forwarded-Host": "attacker.invalid",
                "X-Forwarded-Proto": "http",
                "X-Forwarded-Role": "admin",
                "Connection": "X-Leak-Claim",
                "X-Leak-Claim": "never-forwarded",
                "Accept": "application/json",
            },
        )
        assert health.status_code == 200
        assert health.json() == {"healthy": True}
        assert len(forwarded) == provider_before + 1
        owner = forwarded[-1]
        assert owner.url.host == "briareus-rauthy"
        assert owner.headers["host"] == "briareus.koba-nexus.ru"
        assert owner.headers["x-forwarded-host"] == "briareus.koba-nexus.ru"
        assert owner.headers["x-forwarded-proto"] == "https"
        assert "x-forwarded-user" not in owner.headers
        assert "x-forwarded-role" not in owner.headers
        assert "x-leak-claim" not in owner.headers
        # HTTPX may add its OWN connection/transport framing; the
        # caller's Connection: X-Leak-Claim is never relayed.
        assert owner.headers.get("connection", "").casefold() != "x-leak-claim"
        print("RAUTHY_CANONICAL_PROXY_CLAIMS_AND_CONNECTION_HOP_PASS")

        # The path is intentionally NOT a declared native-login BFF route.
        # Only the Control Panel API may decide which native challenge
        # endpoint to register. The Gateway merely preserves the exact
        # HTTP request/cookie/CSRF body without taking password ownership.
        example = "/api/v1/auth/_fixture/challenge"
        body = b'{"example":"untrusted request; no credential or user proof"}'
        reply = await browser.post(
            example,
            content=body,
            headers={
                "Content-Type": "application/json",
                "Origin": _ORIGIN,
                "Cookie": "untrusted_session=not_a_user",
                "X-Forwarded-User": "spoofed-user",
            },
        )
        assert reply.status_code == 503, reply.status_code
        assert reply.json() == {"detail": "native_login_source_not_enabled"}
        owner = forwarded[-1]
        assert owner.url.host == "briareus-control-panel-api"
        assert owner.url.path == example
        assert await owner.aread() == body
        assert owner.headers.get("cookie") == "untrusted_session=not_a_user"
        assert owner.headers.get("origin") == _ORIGIN
        assert "x-forwarded-user" not in owner.headers
        assert all(
            req.url.host == "briareus-control-panel-api" for req in forwarded[provider_before + 1 :]
        )

        # Source routes below are NOW real Backend owner endpoints. Probe
        # their exact opaque HTTP transport with fixture replies only;
        # the independently running real Rauthy/Valkey flow is checked
        # by smoke_native_bff_start_pow.py outside this source test.
        native_body = b"{}"
        native = await browser.post(
            "/api/v1/auth/start",
            content=native_body,
            headers={
                "Content-Type": "application/json",
                "Origin": _ORIGIN,
                "X-Forwarded-User": "spoofed",
            },
        )
        assert native.status_code == 201
        assert native.json()["stage"] == "first_factor_required"
        assert native.json()["authenticated"] is False
        assert native.headers["cache-control"] == "no-store"
        native_cookies = native.headers.get_list("set-cookie")
        assert len(native_cookies) == 1
        assert native_cookies[0].startswith("__Host-briareus_native_transaction=")
        assert "__Host-RauthySession" not in native_cookies[0]
        owner = forwarded[-1]
        assert owner.url.path == "/api/v1/auth/start"
        assert owner.headers.get("origin") == _ORIGIN
        assert owner.headers.get("content-length") == "2"
        assert await owner.aread() == native_body
        assert not any(k.startswith("x-forwarded-") for k in owner.headers)

        challenge = await browser.post(
            "/api/v1/auth/pow",
            content=native_body,
            headers={
                "Content-Type": "application/json",
                "Origin": _ORIGIN,
                "Cookie": native_cookies[0].split(";", 1)[0],
            },
        )
        assert challenge.status_code == 200
        assert challenge.json()["authenticated"] is False
        assert "set-cookie" not in challenge.headers
        owner = forwarded[-1]
        assert owner.url.path == "/api/v1/auth/pow"
        assert owner.headers.get("cookie") == native_cookies[0].split(";", 1)[0]
        assert await owner.aread() == native_body

        # Newly added Backend first-factor and cancel stay opaque BFF calls.
        # Passing a fixture request through Gateway is not submitting a real
        # credential or accepting an upstream MFA continuation.
        capabilities = await browser.get("/api/v1/auth/capabilities")
        assert capabilities.status_code == 200
        assert capabilities.json() == {
            "protocol": "rauthy-native-v1",
            "first_factor": "password",
            "pow": "client-solved",
            "cancel": True,
            "continuations": [],
        }
        assert "set-cookie" not in capabilities.headers
        owner = forwarded[-1]
        assert owner.url.path == "/api/v1/auth/capabilities"
        assert owner.method == "GET"

        negative_body = b'{"untrusted":"invalid-noncredential-request"}'
        continuation = await browser.post(
            "/api/v1/auth/first-factor",
            content=negative_body,
            headers={
                "Content-Type": "application/json",
                "Origin": _ORIGIN,
                "Cookie": native_cookies[0].split(";", 1)[0],
                "X-Forwarded-User": "forged",
            },
        )
        assert continuation.status_code == 409
        assert continuation.json()["authenticated"] is False
        assert continuation.json()["continuation_available"] is False
        assert "set-cookie" not in continuation.headers
        assert continuation.headers["cache-control"] == "no-store"
        owner = forwarded[-1]
        assert owner.url.path == "/api/v1/auth/first-factor"
        assert await owner.aread() == negative_body
        assert owner.headers["content-length"] == str(len(negative_body))
        assert owner.headers["cookie"] == native_cookies[0].split(";", 1)[0]
        assert not any(key.startswith("x-forwarded-") for key in owner.headers)

        cancel = await browser.post(
            "/api/v1/auth/cancel",
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                "Origin": _ORIGIN,
                "Cookie": native_cookies[0].split(";", 1)[0],
            },
        )
        assert cancel.status_code == 204
        assert not cancel.content
        assert cancel.headers["cache-control"] == "no-store"
        assert len(cancel.headers.get_list("set-cookie")) == 1
        assert "Max-Age=0" in cancel.headers["set-cookie"]
        assert "HttpOnly" in cancel.headers["set-cookie"]
        owner = forwarded[-1]
        assert owner.url.path == "/api/v1/auth/cancel"
        assert owner.headers["content-length"] == "2"
        assert await owner.aread() == b"{}"
        print("NATIVE_BFF_CAPABILITIES_FIRST_FACTOR_DENY_AND_CANCEL204_TRANSPORT_PASS")

        # Multiple Content-Length fields or conflicting transfer framing
        # may not be normalized into an apparently valid native POST by
        # the Gateway, even if each declared length looks syntactically 2.
        for unsafe in (
            [(b"Content-Length", b"2"), (b"Content-Length", b"2")],
            [(b"Content-Length", b"2"), (b"Transfer-Encoding", b"chunked")],
            [(b"Content-Length", b"2,2")],
            [(b"Content-Length", b"9223372036854775808")],
        ):
            old_count = len(forwarded)
            bad = await browser.post(
                "/api/v1/auth/start",
                content=b"{}",
                headers=[
                    (b"Origin", _ORIGIN.encode("ascii")),
                    (b"Content-Type", b"application/json"),
                    *unsafe,
                ],
            )
            assert bad.status_code == 400, (unsafe, bad.status_code)
            assert len(forwarded) == old_count

        # The future owner-native BFF must be able to issue two distinct
        # Secure Set-Cookie fields for a pre-auth challenge and carry a
        # same-origin 303 without Gateway merging, dropping or minting them.
        # These are test fixtures, NOT an authenticated Rauthy login.
        preauth_path = "/api/v1/auth/_fixture/response"
        upstream_before = len(forwarded)
        preauth_body = b'{"provider_challenge":"test-only-opaque"}'
        preauth = await browser.post(
            preauth_path,
            content=preauth_body,
            headers={
                "Content-Type": "application/json",
                "Origin": _ORIGIN,
                "X-CSRF-Token": "opaque-client-csrf",
                "X-Forwarded-User": "forged",
                "X-Forwarded-Role": "operator",
                "X-Forwarded-Principal": "forged",
            },
        )
        assert preauth.status_code == 202
        assert preauth.json() == {"state": "challenge_pending"}
        assert preauth.headers["cache-control"] == "no-store"
        assert len(preauth.headers.get_list("set-cookie")) == 2
        assert all(
            "HttpOnly" in value and "Secure" in value
            for value in preauth.headers.get_list("set-cookie")
        )
        assert len(forwarded) == upstream_before + 1
        owner = forwarded[-1]
        assert owner.url.host == "briareus-control-panel-api"
        assert owner.url.path == preauth_path
        assert owner.headers["x-csrf-token"] == "opaque-client-csrf"
        assert await owner.aread() == preauth_body
        assert not any(header.startswith("x-forwarded-") for header in owner.headers)

        redirected = await browser.get(
            "/api/v1/auth/_fixture/redirect",
            follow_redirects=False,
        )
        assert redirected.status_code == 303
        assert redirected.headers["location"] == _ORIGIN + "/panel/"
        assert "Max-Age=0" in redirected.headers["set-cookie"]
        assert redirected.headers["cache-control"] == "no-store"

        count = len(forwarded)
        rejected = await browser.post(
            example,
            headers={"Origin": "https://attacker.invalid"},
            content=body,
        )
        assert rejected.status_code == 403
        assert len(forwarded) == count

        handler._client = None
        blocked = await browser.post(example, content=body)
        assert blocked.status_code == 502

    print("NATIVE_BFF_FIXED_CONTENT_LENGTH_AND_FRAMING_REJECTION_PASS")
    print("NATIVE_BFF_CURRENT_INIT201_AND_POW200_TRANSPORT_PASS")
    print("NATIVE_BFF_MULTIPLE_SECURE_COOKIES_CSRF_AND_303_RELAY_PASS")
    print("NATIVE_CONTROL_PANEL_BFF_ONLY_TRANSPORT_FAIL_CLOSED_PASS")
    print("HOSTED_RAUTHY_UI_STATIC_ROUTES_REMOVED_PASS")
    print("NOT_PROVEN: native login, Rauthy signed identity, Platform Project or Cedar")


if __name__ == "__main__":
    asyncio.run(_run())
