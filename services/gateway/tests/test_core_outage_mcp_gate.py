"""Core/Execution split: no stale mcp.connect admission during Core outages.

All positive decision responses here are controlled transport fixtures.
The Files execution owner always independently DENIES business effects.
No real bearer, signed User, Cedar permit or Files root is created.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
from bridge._mcp_admission import PrivateAdmissionReply

from bridge.thin_gateway import build_app

_ORIGIN = "https://briareus.koba-nexus.ru"
_BODY = b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
_CONTEXT = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "Authorization": "Bearer opaque_test_fixture_not_a_verified_token",
    "Origin": _ORIGIN,
    "X-Briareus-Project-UUID": "12345678-1234-4234-8234-123456789abc",
    "X-Briareus-Agent-Session-UUID": "12345678-1234-4234-8234-123456789abd",
    "X-Briareus-Grant-Revision": "7",
}


class _Bytes(httpx.AsyncByteStream):
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.payload

    async def aclose(self) -> None:
        pass


class _Decisions:
    def __init__(self) -> None:
        self.mode = "unavailable"
        self.calls = 0
        self.replies = 0
        self.bearers: list[str] = []

    async def decide(self, *, bearer: str, body: bytes) -> PrivateAdmissionReply:
        self.calls += 1
        self.bearers.append(bearer)
        assert bearer == _CONTEXT["Authorization"]
        assert b'"action":"mcp.connect"' in body
        assert b'"hand"' not in body and b'"resource"' not in body
        assert len(body) < 8192
        if self.mode == "unavailable":
            raise ConnectionError("controlled private Core Access outage")
        if self.mode == "untrusted":
            return PrivateAdmissionReply(503, b'{"allowed":true}')
        if self.mode == "identity_denied":
            return PrivateAdmissionReply(401, b"{}")
        if self.mode == "access_denied":
            return PrivateAdmissionReply(403, b"{}")
        if self.mode == "bad_reply":
            return PrivateAdmissionReply(200, b'{"allowed":1}')
        if self.mode == "bad_duplicate":
            return PrivateAdmissionReply(200, b'{"allowed":true,"allowed":true}')
        if self.mode == "bounded_wait":
            await asyncio.Event().wait()
        if self.mode == "one_fixture_admission":
            self.replies += 1
            return PrivateAdmissionReply(200, b'{"allowed":true}')
        raise AssertionError("unknown fixture mode")


async def run() -> None:
    incoming_to_hand: list[httpx.Request] = []

    def files_hand(request: httpx.Request) -> httpx.Response:
        incoming_to_hand.append(request)
        assert request.url.host == "briareus-files"
        assert request.url.path == "/mcp"
        assert request.method == "POST"
        assert request.headers["authorization"] == _CONTEXT["Authorization"]
        assert request.headers["x-briareus-grant-revision"] == "7"
        # An independent Hand PEP remains closed. The coarse
        # test decision must never cause a real Files content read.
        return httpx.Response(
            503,
            headers={"content-type": "application/json", "cache-control": "no-store"},
            stream=_Bytes(b'{"code":"FILES_AUTHORIZATION_UNAVAILABLE"}'),
        )

    private = _Decisions()
    app = build_app(private_decision=private)
    route = next(item for item in app.routes if getattr(item, "path", "") == "/hands/files/mcp")
    gateway = route.endpoint.__self__
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(files_hand)) as upstream,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=_ORIGIN,
            follow_redirects=False,
            timeout=5,
        ) as browser,
    ):
        gateway._client = upstream
        for mode, expected in (
            ("unavailable", 503),
            ("untrusted", 503),
            ("identity_denied", 401),
            ("access_denied", 403),
            ("bad_reply", 503),
            ("bad_duplicate", 503),
        ):
            private.mode = mode
            before = len(incoming_to_hand)
            response = await browser.post("/hands/files/mcp", content=_BODY, headers=_CONTEXT)
            assert response.status_code == expected, (mode, response.status_code)
            assert response.headers["cache-control"] == "no-store"
            assert len(incoming_to_hand) == before, mode
            assert gateway._slots._value == 64 and not gateway._open

        # Timeout must not silently retain prior admission.
        from bridge import _mcp_admission

        original_limit = _mcp_admission._DECISION_TIMEOUT_SECONDS
        _mcp_admission._DECISION_TIMEOUT_SECONDS = 0.03
        try:
            private.mode = "bounded_wait"
            waiting = await browser.post("/hands/files/mcp", content=_BODY, headers=_CONTEXT)
            assert waiting.status_code == 503
        finally:
            _mcp_admission._DECISION_TIMEOUT_SECONDS = original_limit
        assert not incoming_to_hand

        # Even a test-only 'allowed' coarse reply does NOT bypass the
        # independent Files Hand business PEP: its actual response denies.
        private.mode = "one_fixture_admission"
        started = await browser.post("/hands/files/mcp", content=_BODY, headers=_CONTEXT)
        assert started.status_code == 503
        assert started.json()["code"] == "FILES_AUTHORIZATION_UNAVAILABLE"
        assert len(incoming_to_hand) == 1

        # Simulate Core becoming unavailable immediately after a prior
        # provisional connection. Gateway must seek a FRESH decision.
        private.mode = "unavailable"
        denied = await browser.post("/hands/files/mcp", content=_BODY, headers=_CONTEXT)
        assert denied.status_code == 503
        assert len(incoming_to_hand) == 1
        assert private.calls >= 9 and private.replies == 1
        assert gateway._slots._value == 64
        assert not gateway._pending and not gateway._streams and not gateway._open

        # Neither a browser cookie nor a forged identity proxy header
        # can replace independent current Authorization.
        cookie = await browser.post(
            "/hands/files/mcp",
            content=_BODY,
            headers={**_CONTEXT, "Cookie": "opaque-not-a-grant"},
        )
        assert cookie.status_code == 400
        assert len(incoming_to_hand) == 1
    print("GATEWAY_CORE_UNAVAILABLE_DENIES_HAND_BEFORE_FORWARD_PASS")
    print("GATEWAY_CURRENT_CONNECTION_DECISION_NOT_CACHED_AFTER_RECOVERY_OR_OUTAGE_PASS")
    print("GATEWAY_TEST_ONLY_COARSE_ALLOW_STILL_HAND_DENIES_NO_FILES_CONTENT_PASS")
    print("NOT_ACCEPTED: private peer identity, real signed bearer, Cedar or Files content")


asyncio.run(run())
