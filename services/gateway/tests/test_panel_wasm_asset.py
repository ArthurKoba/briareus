"""Real Panel sPoW WASM static path; exact type/size/Host and no route widening.

A local ASGI transport fixture is not a user login or a real Rauthy token.
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
    response_kind = "valid"

    def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal response_kind
        seen.append(request)
        assert request.url.host == "briareus-control-panel-ui"
        assert request.url.port == 8080
        assert request.url.path == _ASSET
        assert request.headers["accept"] == "*/*"
        assert request.headers["accept-encoding"] == "identity"
        if response_kind == "wrong_mime":
            return httpx.Response(
                200, headers={"content-type": "text/html"}, stream=_Bytes(b"html")
            )
        if response_kind == "upstream_not_found":
            return httpx.Response(
                404, headers={"content-type": "application/wasm"}, stream=_Bytes(b"")
            )
        if response_kind == "oversized":
            return httpx.Response(
                200,
                headers={"content-type": "application/wasm", "content-length": "65537"},
                stream=_Bytes(b"a" * 65_537),
            )
        if response_kind == "underreported":
            return httpx.Response(
                200,
                headers={"content-type": "application/wasm", "content-length": "8"},
                stream=_Bytes(b"a" * 65_537),
            )
        assert response_kind == "valid"
        return httpx.Response(
            200,
            headers={"content-type": "application/wasm"},
            stream=_Bytes(_WASM_HEADER),
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as owner,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=_ORIGIN,
            follow_redirects=False,
        ) as browser,
    ):
        handler._client = owner

        valid = await browser.get(_ASSET)
        assert valid.status_code == 200, valid.status_code
        assert valid.content == _WASM_HEADER
        assert valid.headers["content-type"].startswith("application/wasm")
        assert valid.headers["x-content-type-options"] == "nosniff"
        assert valid.headers["cache-control"] == "public, max-age=60"
        assert len(seen) == 1 and seen[-1].method == "GET"

        head = await browser.head(_ASSET)
        assert head.status_code == 200 and head.content == b""
        assert seen[-1].method == "HEAD"

        # No unversioned root, query variants, prefix-less routing, scripts,
        # traversal or extension case confusion can reach the UI origin.
        for path in (
            "/assets/spow-wasm_bg-GdN2RRkx.wasm",
            _ASSET + "?x=1",
            _ASSET + "/more",
            "/panel/assets/another.wasm/../private",
            "/panel/assets/..%2fsecret.wasm",
            "/panel/assets/bundle.WASM",
        ):
            count = len(seen)
            result = await browser.get(path)
            assert result.status_code == 404, (path, result.status_code)
            assert len(seen) == count, path
        count = len(seen)
        posted = await browser.post(_ASSET, content=b"{}")
        assert posted.status_code == 404 and len(seen) == count

        # Only correct upstream WASM bytes, MIME and bounded size may cross
        # the public origin. Failure is a closed Gateway 502, not HTML 200.
        for kind in ("wrong_mime", "upstream_not_found", "oversized", "underreported"):
            response_kind = kind
            result = await browser.get(_ASSET)
            assert result.status_code == 502, (kind, result.status_code)
            assert result.json()["code"] == "GATEWAY_UPSTREAM_UNAVAILABLE"

    print("PUBLIC_PANEL_WASM_WORKER_DEPENDENCY_ROUTED_WITH_EXACT_MIME_AND_SIZE_PASS")
    print("ROOT_QUERY_ALIAS_METHOD_WRONG_MIME_AND_OVERSIZED_ASSET_DENIED_PASS")
    print("NO_PROVIDER_SECRETS_USER_LOGIN_OR_CEDAR_PERMISSION")


if __name__ == "__main__":
    asyncio.run(main())
