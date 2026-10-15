"""Gateway native cancel may overtake a pending first-factor HTTP exchange.

The upstream is a controlled BFF-shaped transport fixture, not an OAuth
password verifier. Only Backend/Valkey can atomically revoke an actual
one-use transaction and issue or refuse a signed user session.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress

import httpx

from bridge.thin_gateway import build_app

_ORIGIN = "https://briareus.koba-nexus.ru"
_PENDING_COOKIE = (
    "__Host-briareus_native_transaction=opaque_controlled_fixture;"
    " HttpOnly; Secure; Path=/; SameSite=Lax"
)


class _Body(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def __aiter__(self) -> AsyncIterator[bytes]:
        if self.content:
            yield self.content

    async def aclose(self) -> None:
        pass


async def run() -> None:
    admitted = asyncio.Event()
    cancelled = asyncio.Event()
    forwarded: list[tuple[str, bytes, str, str]] = []

    async def owner(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        forwarded.append(
            (
                request.url.path,
                body,
                request.headers.get("cookie", ""),
                request.headers.get("origin", ""),
            )
        )
        if request.url.path == "/api/v1/auth/first-factor":
            admitted.set()
            await cancelled.wait()
            return httpx.Response(
                401,
                headers={"content-type": "application/json", "cache-control": "no-store"},
                stream=_Body(b'{"error":{"code":"NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED"}}'),
            )
        if request.url.path == "/api/v1/auth/cancel":
            cancelled.set()
            return httpx.Response(
                204,
                headers=[
                    ("cache-control", "no-store"),
                    (
                        "set-cookie",
                        _PENDING_COOKIE.split("=", 1)[0]
                        + "=; HttpOnly; Secure; Path=/; SameSite=Lax; Max-Age=0",
                    ),
                ],
                stream=_Body(b""),
            )
        raise AssertionError("fixed native BFF owner received an unexpected path")

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
            timeout=5,
        ) as browser,
    ):
        gateway._client = upstream
        headers = {
            "Origin": _ORIGIN,
            "Content-Type": "application/json",
            "Cookie": _PENDING_COOKIE.split(";", 1)[0],
        }
        first = asyncio.create_task(
            browser.post(
                "/api/v1/auth/first-factor",
                content=b'{"untrusted":"opaque-not-a-credential"}',
                headers=headers,
            )
        )
        try:
            await asyncio.wait_for(admitted.wait(), 2)
            assert gateway._slots._value == 63
            assert len(gateway._pending) == 1

            abort = await asyncio.wait_for(
                browser.post("/api/v1/auth/cancel", content=b"{}", headers=headers), 2
            )
            assert abort.status_code == 204
            assert abort.content == b""
            assert len(abort.headers.get_list("set-cookie")) == 1
            assert "Max-Age=0" in abort.headers["set-cookie"]
            assert abort.headers["cache-control"] == "no-store"

            completed = await asyncio.wait_for(first, 2)
            assert completed.status_code == 401
            assert completed.json()["error"]["code"] == "NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED"
            assert "set-cookie" not in completed.headers
        finally:
            cancelled.set()
            if not first.done():
                first.cancel()
                with suppress(asyncio.CancelledError):
                    await first
        assert [item[0] for item in forwarded] == [
            "/api/v1/auth/first-factor",
            "/api/v1/auth/cancel",
        ]
        assert forwarded[0][1] == b'{"untrusted":"opaque-not-a-credential"}'
        assert forwarded[1][1] == b"{}"
        assert all(item[2] == headers["Cookie"] and item[3] == _ORIGIN for item in forwarded)
        assert not gateway._pending
        assert not gateway._streams
        assert not gateway._open
        assert gateway._slots._value == 64
    print("GATEWAY_NATIVE_FIRST_FACTOR_PENDING_CANCEL_OVERTAKES_AND_DRAINS_PASS")
    print("GATEWAY_INFLIGHT_COOKIE_BODY_CONTINUITY_AND_NO_FAKE_SESSION_PASS")
    print("NOT_PROVEN: Backend atomic logout, upstream Rauthy login, signed user or Cedar")


asyncio.run(run())
