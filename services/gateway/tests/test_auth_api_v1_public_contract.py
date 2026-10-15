"""Public versioned auth paths are transparent; retired native is NOT an alias.

No mocked signed User or successful first-factor decision is created here.
MockTransport represents only the fixed API owner and verifies that the
Gateway does not translate or forward any retired route/bearer cookie.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
from bridge._api_contract import AUTH_V1_PREFIX, REGISTERED_RAUTHY_CALLBACK_PATH, retired_auth_path

from bridge.thin_gateway import build_app

_ORIGIN = "https://briareus.koba-nexus.ru"


class _Wire(httpx.AsyncByteStream):
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def __aiter__(self) -> AsyncIterator[bytes]:
        if self.payload:
            yield self.payload

    async def aclose(self) -> None:
        pass


async def main() -> None:
    assert AUTH_V1_PREFIX == "/api/v1/auth"
    for old in (
        "/api/auth/native",
        "/api/auth/native/start",
        "/api/auth/native/cancel",
        "/api/auth/native/pow",
        "/api/auth/native/first-factor",
        "/api/auth/oidc/me",
        "/api/auth/oidc/session",
        "/api/auth/oidc/logout",
        "/api/auth/oidc/callback/extra",
        "/api/auth/oidc/callback%2fextra",
        "/api/auth/n%61tive/start",
        "/api/auth%2fnative/first-factor",
        "/api/auth/%256eative/pow",
        "/api/%2561uth/%256eative/start",
    ):
        assert retired_auth_path(raw_path=old, decoded_path=old, method="POST"), old
    assert not retired_auth_path(
        raw_path=REGISTERED_RAUTHY_CALLBACK_PATH,
        decoded_path=REGISTERED_RAUTHY_CALLBACK_PATH,
        method="GET",
    )
    assert retired_auth_path(
        raw_path="/api/auth/oidc/%63allback",
        decoded_path=REGISTERED_RAUTHY_CALLBACK_PATH,
        method="GET",
    )  # even encoded callback is NOT a registered redirect URI.
    assert retired_auth_path(
        raw_path=REGISTERED_RAUTHY_CALLBACK_PATH,
        decoded_path=REGISTERED_RAUTHY_CALLBACK_PATH,
        method="POST",
    )
    for new in (
        "/api/v1/auth",
        "/api/v1/auth/start",
        "/api/v1/auth/first-factor",
        REGISTERED_RAUTHY_CALLBACK_PATH,  # exact Rauthy registered redirect only
        "/api/v1/auth/me",
    ):
        assert not retired_auth_path(raw_path=new, decoded_path=new, method="GET"), new

    visited: list[tuple[str, bytes, str]] = []

    async def owner(request: httpx.Request) -> httpx.Response:
        payload = await request.aread()
        assert request.url.host == "briareus-control-panel-api"
        visited.append((request.url.path, payload, request.headers.get("origin", "")))
        if request.url.path == REGISTERED_RAUTHY_CALLBACK_PATH:
            assert request.method == "GET"
            return httpx.Response(
                400,
                headers={"content-type": "application/json"},
                stream=_Wire(b'{"error":{"code":"OIDC_CALLBACK_STATE_INVALID"}}'),
            )
        if request.url.path == "/api/v1/auth/start":
            assert request.method == "POST" and payload == b"{}"
            assert request.headers["content-length"] == "2"
            assert request.headers["content-type"] == "application/json"
            return httpx.Response(
                201,
                headers=[
                    (b"content-type", b"application/json"),
                    (
                        b"set-cookie",
                        b"__Host-briareus_native_transaction=opaque_fixture;"
                        b" HttpOnly; Secure; SameSite=Lax; Path=/",
                    ),
                    (b"cache-control", b"no-store"),
                ],
                stream=_Wire(b'{"stage":"first_factor_required","authenticated":false}'),
            )
        if request.url.path == "/api/v1/files/read":
            # Future browser content reads MUST use the owner BFF.
            # This fixture cannot invent signed User/Cedar/Files mapping.
            assert request.method == "POST"
            assert request.headers["origin"] == _ORIGIN
            assert request.headers["content-type"] == "application/json"
            assert b"untrusted" in payload
            return httpx.Response(
                403,
                headers={"content-type": "application/json", "cache-control": "no-store"},
                stream=_Wire(b'{"error":{"code":"FILES_ACCESS_DENIED"}}'),
            )
        if request.url.path == "/api/v1/auth/cancel":
            assert payload == b"{}"
            assert request.headers["cookie"].startswith("__Host-briareus_native_transaction=")
            return httpx.Response(
                204,
                headers=[
                    (
                        b"set-cookie",
                        b"__Host-briareus_native_transaction=; HttpOnly; Secure; Path=/; Max-Age=0",
                    ),
                    (b"cache-control", b"no-store"),
                ],
                stream=_Wire(b""),
            )
        return httpx.Response(
            404,
            headers={"content-type": "application/json"},
            stream=_Wire(b'{"error":{"code":"OWNER_VERSIONED_ROUTE_UNCONFIGURED"}}'),
        )

    app = build_app()
    gateway = next(
        route.endpoint.__self__
        for route in app.routes
        if getattr(route, "path", "") == "/api/{path:path}"
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(owner)) as upstream,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=_ORIGIN,
            follow_redirects=False,
        ) as browser,
    ):
        gateway._client = upstream
        for path in (
            "/api/auth/native",
            "/api/auth/native/start",
            "/api/auth/native/pow",
            "/api/auth/native/cancel",
            "/api/auth/native/first-factor",
            "/api/auth/oidc/files/read",
            "/api/auth/n%61tive/start",
            "/api/auth%2Fnative/cancel",
            "/api/auth/%256eative/pow",
            "/api/%2561uth/%256eative/start",
        ):
            before = len(visited)
            blocked = await browser.post(
                path,
                content=b'{"sensitive":"never-forwarded"}',
                headers={
                    "Content-Type": "application/json",
                    "Origin": _ORIGIN,
                    "Cookie": "session=not-a-real-user",
                },
            )
            assert blocked.status_code == 404, (path, blocked.status_code)
            assert blocked.json() == {"code": "AUTH_API_ROUTE_RETIRED"}
            assert blocked.headers["cache-control"] == "no-store"
            assert len(visited) == before, ("legacy route contacted Backend", path)

        # There is no wildcard Core private REST proxy behind /api.
        # A future internal endpoint cannot become public merely because
        # Backend adds it while a historical Gateway route stays broad.
        for unversioned in (
            "/api/private",
            "/api/internal/v1/authorization/files/read-decision",
            "/api/v2/auth/start",
            "/api/health/live",
            "/api/v1%2Fauth/start",
            "/api/v1/auth%2Fstart",
            "/api/v1//auth/start",
            "/api/v1/auth/%2e%2e/start",
        ):
            before = len(visited)
            rejected = await browser.post(
                unversioned,
                content=b'{"sensitive":"untrusted"}',
                headers={"Content-Type": "application/json", "Origin": _ORIGIN},
            )
            assert rejected.status_code == 404, (unversioned, rejected.status_code)
            assert rejected.json() == {"code": "API_ROUTE_NOT_PUBLIC"}, unversioned
            assert len(visited) == before, unversioned

        old_count = len(visited)
        unexpected_post = await browser.post(
            REGISTERED_RAUTHY_CALLBACK_PATH,
            content=b"not-an-oauth-code",
            headers={"Origin": _ORIGIN},
        )
        assert unexpected_post.status_code == 404
        assert len(visited) == old_count
        previous = len(visited)
        exact_callback = await browser.get(REGISTERED_RAUTHY_CALLBACK_PATH + "?state=untrusted")
        assert exact_callback.status_code == 400
        assert len(visited) == previous + 1
        assert visited[-1][0] == REGISTERED_RAUTHY_CALLBACK_PATH
        assert visited[-1][1] == b""
        payload = await browser.post(
            AUTH_V1_PREFIX + "/start",
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                "Origin": _ORIGIN,
                "X-Forwarded-User": "forged",
            },
        )
        assert payload.status_code == 201
        assert payload.json()["authenticated"] is False
        assert len(payload.headers.get_list("set-cookie")) == 1
        assert visited[-1] == (AUTH_V1_PREFIX + "/start", b"{}", _ORIGIN)

        cleared = await browser.post(
            AUTH_V1_PREFIX + "/cancel",
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                "Origin": _ORIGIN,
                "Cookie": payload.headers["set-cookie"].split(";", 1)[0],
            },
        )
        assert cleared.status_code == 204 and cleared.content == b""
        assert "Max-Age=0" in cleared.headers["set-cookie"]
        assert visited[-1] == (AUTH_V1_PREFIX + "/cancel", b"{}", _ORIGIN)

        private_before = len(visited)
        untrusted = b'{"path":"untrusted/path","max_bytes":128}'
        blocked_file = await browser.post(
            "/api/v1/files/read",
            content=untrusted,
            headers={
                "Content-Type": "application/json",
                "Origin": _ORIGIN,
                "Cookie": "not-a-signed-user",
                "X-Forwarded-User": "untrusted-actor",
            },
        )
        assert blocked_file.status_code == 403
        assert blocked_file.json() == {"error": {"code": "FILES_ACCESS_DENIED"}}
        assert blocked_file.headers["cache-control"] == "no-store"
        assert "set-cookie" not in blocked_file.headers
        assert len(visited) == private_before + 1
        assert visited[-1] == ("/api/v1/files/read", untrusted, _ORIGIN)

        for method, path in (
            ("GET", AUTH_V1_PREFIX + "/capabilities"),
            ("POST", AUTH_V1_PREFIX + "/first-factor"),
            ("POST", AUTH_V1_PREFIX + "/pow"),
        ):
            before = len(visited)
            response = await browser.request(
                method,
                path,
                headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
                content=b"{}" if method == "POST" else None,
            )
            assert response.status_code == 404  # This test owner is deliberately unconfigured.
            assert len(visited) == before + 1
            assert visited[-1][0] == path
        assert gateway._slots._value == 64
        assert not gateway._open and not gateway._pending and not gateway._streams
    print("AUTH_V1_PUBLIC_PATH_EXACT_BACKEND_FORWARDING_NO_REWRITE_PASS")
    print("OLD_UNVERSIONED_AUTH_EXCEPT_REGISTERED_CALLBACK_DENY_PASS")
    print("PRIVATE_AND_NONCANONICAL_API_NOT_PROXYABLE_TO_CORE_PASS")
    print("AUTH_V1_FILES_CONTENT_BFF_DENY_NO_DIRECT_HAND_ACCESS_PASS")
    print("AUTH_V1_NATIVE_TRANSACTION_201_AND_CANCEL204_TRANSPORT_ONLY_PASS")
    print("NOT_ACCEPTED: Backend v1 rollout, signed login, Project/Cedar or Files")


asyncio.run(main())
