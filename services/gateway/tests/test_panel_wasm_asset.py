"""Panel is a transparent fixed-upstream proxy, not a Vite static server.

These ASGI fixtures prove unknown asset extensions/MIME, HTTP status, headers,
body, cookies, exact method and query reach the UI owner unchanged. No login.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx

from bridge.thin_gateway import build_app

_ORIGIN = "https://briareus.koba-nexus.ru"
_ASSET = "/panel/assets/spow-wasm_bg-GdN2RRkx.wasm"
_WASM_HEADER = b"\x00asm\x01\x00\x00\x00"


class _Bytes(httpx.AsyncByteStream):
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.payload

    async def aclose(self) -> None:
        pass


async def main() -> None:
    app = build_app()
    handler = next(
        route.endpoint.__self__
        for route in app.routes
        if getattr(route, "path", "") == "/panel/{path:path}"
    )
    seen: list[httpx.Request] = []

    async def ui(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.host == "briareus-control-panel-ui"
        assert request.url.port == 8080
        assert request.headers["host"] == "briareus.koba-nexus.ru"
        assert "x-forwarded-user" not in request.headers
        assert "x-forwarded-host" not in request.headers
        assert request.headers.get("connection", "").lower() != "x-steal"
        if request.url.path == "/panel/assets/undefined-future-extension.blob":
            return httpx.Response(
                206,
                headers=[
                    (b"content-type", b"application/x-custom-ui-asset"),
                    (b"cache-control", b"public, max-age=90"),
                    (b"set-cookie", b"ui_a=; Path=/; Secure; HttpOnly; Max-Age=0"),
                    (b"set-cookie", b"ui_b=; Path=/; Secure; HttpOnly; Max-Age=0"),
                ],
                stream=_Bytes(b"opaque-ui-owner-content"),
            )
        if request.url.path == "/panel/assets/missing.hash":
            return httpx.Response(
                404,
                headers={"content-type": "text/plain", "cache-control": "no-cache"},
                stream=_Bytes(b"missing-ui-file"),
            )
        if request.url.path == "/panel/assets/unexpected":
            return httpx.Response(
                503,
                headers={"content-type": "application/json"},
                stream=_Bytes(b'{"owner":"unavailable"}'),
            )
        if request.url.path == "/panel/" and request.method == "GET":
            # Gateway no longer parses HTML and does not mandate "noindex".
            return httpx.Response(
                200,
                headers={"content-type": "text/html", "cache-control": "no-store"},
                stream=_Bytes(b"<html><main>Panel owner controls HTML</main></html>"),
            )
        if request.url.path == "/panel/assets/some.js" and request.method == "POST":
            assert await request.aread() == b"future-ui-body"
            assert request.headers["content-type"] == "text/plain"
            assert request.headers["cookie"] == "opaque_cookie=private-fixture"
            return httpx.Response(
                405,
                headers={"content-type": "text/plain"},
                stream=_Bytes(b"owner-method-denied"),
            )
        if request.url.path == _ASSET:
            return httpx.Response(
                200,
                headers={
                    "content-type": "application/octet-stream",
                    "cache-control": "max-age=300",
                },
                stream=_Bytes(b"" if request.method == "HEAD" else _WASM_HEADER),
            )
        assert request.url.path.startswith("/panel/"), request.url.path
        return httpx.Response(
            404, headers={"content-type": "text/plain"}, stream=_Bytes(b"ui-owner-404")
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(ui)) as owner,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=_ORIGIN,
            follow_redirects=False,
        ) as browser,
    ):
        handler._client = owner

        wasm = await browser.get(_ASSET)
        assert wasm.status_code == 200 and wasm.content == _WASM_HEADER
        assert wasm.headers["content-type"] == "application/octet-stream"
        assert wasm.headers["cache-control"] == "max-age=300"
        assert seen[-1].url.path == _ASSET

        head = await browser.head(_ASSET)
        assert head.status_code == 200 and head.content == b""
        assert seen[-1].method == "HEAD"

        query = await browser.get(_ASSET + "?cache=hashed")
        assert query.status_code == 200 and query.content == _WASM_HEADER
        assert seen[-1].url.query == b"cache=hashed"

        opaque = await browser.get(
            "/panel/assets/undefined-future-extension.blob",
            headers={
                "x-forwarded-user": "forged",
                "x-forwarded-host": "attacker.invalid",
                "Connection": "X-Steal",
                "x-steal": "forged",
            },
        )
        assert opaque.status_code == 206 and opaque.content == b"opaque-ui-owner-content"
        assert opaque.headers["content-type"] == "application/x-custom-ui-asset"
        assert opaque.headers["cache-control"] == "public, max-age=90"
        assert len(opaque.headers.get_list("set-cookie")) == 2

        noindex_not_needed = await browser.get("/panel/")
        assert noindex_not_needed.status_code == 200
        assert b"Panel owner controls HTML" in noindex_not_needed.content

        for path, status, expected in (
            ("/panel/assets/missing.hash", 404, b"missing-ui-file"),
            ("/panel/assets/unexpected", 503, b'{"owner":"unavailable"}'),
        ):
            response = await browser.get(path)
            assert (response.status_code, response.content) == (status, expected), path

        sent = await browser.post(
            "/panel/assets/some.js",
            content=b"future-ui-body",
            headers={"content-type": "text/plain", "cookie": "opaque_cookie=private-fixture"},
        )
        assert sent.status_code == 405 and sent.content == b"owner-method-denied"

        # Gateway retains only namespace/routing and transport controls.
        # It must not become an arbitrary reverse proxy for root assets,
        # deprecated provider static paths, traversal or unregistered Hands.
        for path in (
            "/assets/undefined-future-extension.blob",
            "/_app/immutable/chunks/base.js",
            "/panel//assets/blob.bin",
            "/panel/assets/%2e%2e/admin",
            "/panel/%2fsecret",
            "/hands/not-registered/mcp",
        ):
            before = len(seen)
            rejected = await browser.get(path)
            assert rejected.status_code in {404, 503}, (path, rejected.status_code)
            assert len(seen) == before, path
        redirected = await browser.get("/panel")
        assert redirected.status_code == 308
        assert redirected.headers["location"] == "/panel/"
        assert len(seen) == before

        before = len(seen)
        wrong_host = await browser.get(_ASSET, headers={"host": "untrusted.invalid"})
        assert wrong_host.status_code == 421 and len(seen) == before

        assert not handler._open and handler._slots._value == 64

    print("PANEL_TRANSPARENT_FIXED_UI_STREAM_WASM_FUTURE_MIME_AND_UNKNOWN_ASSETS_PASS")
    print("UPSTREAM_STATUSES_HEADERS_COOKIES_QUERY_METHOD_BODY_RETAINED_PASS")
    print("OFF_ROUTE_TRAVERSAL_FORGED_HOST_DENIED_NO_PRIVILEGED_ACCEPTANCE")


if __name__ == "__main__":
    asyncio.run(main())
