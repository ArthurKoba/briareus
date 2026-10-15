"""Real Gateway route for an anonymous v1 session: exact Backend errors, no login.

All owner replies are inert transport fixtures; a 401 is not signed-in proof.
"""

from __future__ import annotations

import asyncio

import httpx

from bridge.thin_gateway import build_app

_ORIGIN = "https://briareus.koba-nexus.ru"
_PATH = "/api/v1/auth/session"


async def main() -> None:
    forwarded: list[httpx.Request] = []
    mode = "anonymous"

    async def owner(request: httpx.Request) -> httpx.Response:
        forwarded.append(request)
        assert request.url.host == "briareus-control-panel-api"
        assert request.url.path == _PATH and request.url.query == b""
        assert request.headers["host"] == "briareus.koba-nexus.ru"
        assert "x-forwarded-user" not in request.headers
        assert "x-forwarded-host" not in request.headers
        if mode == "anonymous":
            return httpx.Response(
                401,
                headers=[
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                    (b"pragma", b"no-cache"),
                ],
                stream=httpx.ByteStream(b'{"error":{"code":"OIDC_SESSION_REQUIRED"}}'),
            )
        if mode == "realm_mismatch":
            assert request.headers["cookie"].startswith("__Host-briareus_oidc_session=")
            return httpx.Response(
                401,
                headers=[
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                    (b"pragma", b"no-cache"),
                    (
                        b"set-cookie",
                        b"__Host-briareus_oidc_session=; Path=/; Secure; HttpOnly; Max-Age=0",
                    ),
                ],
                stream=httpx.ByteStream(b'{"error":{"code":"OIDC_SESSION_REALM_MISMATCH"}}'),
            )
        if mode == "unavailable":
            return httpx.Response(
                503,
                headers=[
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                    (b"pragma", b"no-cache"),
                ],
                stream=httpx.ByteStream(b'{"error":{"code":"OIDC_SESSION_UNAVAILABLE"}}'),
            )
        raise AssertionError("fixture mode")

    app = build_app()
    gateway = next(
        route.endpoint.__self__
        for route in app.routes
        if getattr(route, "path", "") == "/api/{path:path}"
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(owner)) as upstream,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url=_ORIGIN,
            follow_redirects=False,
        ) as browser,
    ):
        gateway._client = upstream
        for current, expected_code, expected_status, cookie in (
            ("anonymous", "OIDC_SESSION_REQUIRED", 401, None),
            (
                "realm_mismatch",
                "OIDC_SESSION_REALM_MISMATCH",
                401,
                "__Host-briareus_oidc_session=opaque_fixture",
            ),
            ("unavailable", "OIDC_SESSION_UNAVAILABLE", 503, None),
        ):
            mode = current
            headers = {"origin": _ORIGIN, "x-forwarded-user": "forged"}
            if cookie is not None:
                headers["cookie"] = cookie
            reply = await browser.get(_PATH, headers=headers)
            assert (reply.status_code, reply.json()) == (
                expected_status,
                {"error": {"code": expected_code}},
            )
            assert reply.headers["cache-control"] == "no-store"
            assert reply.headers["pragma"] == "no-cache"
            assert "location" not in reply.headers
            assert len(reply.headers.get_list("set-cookie")) == int(cookie is not None)
            if cookie is not None:
                assert "Max-Age=0" in reply.headers["set-cookie"]
                assert forwarded[-1].headers["cookie"] == cookie
            else:
                assert "cookie" not in forwarded[-1].headers
            assert gateway._slots._value == 64 and not gateway._open
        before = len(forwarded)
        refused = await browser.get(_PATH, headers={"host": "attacker.invalid", "origin": _ORIGIN})
        assert refused.status_code == 421 and len(forwarded) == before
        gateway._client = None

    print("GATEWAY_SESSION_V1_BACKEND_401_503_NOSTORE_COOKIE_CLEAR_PASS")
    print("NO_REAL_SIGNED_HUMAN_USER_OR_COMPLETED_LOGIN_IN_FIXTURES")


if __name__ == "__main__":
    asyncio.run(main())
