"""Opaque management-command transport, not authenticated approval acceptance."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx

from bridge.thin_gateway import build_app

ORIGIN = "https://briareus.koba-nexus.ru"
OPERATION = "12345678-1234-4234-8234-123456789abc"
PROJECT = "12345678-1234-4234-8234-123456789abd"
SESSION = "12345678-1234-4234-8234-123456789abe"


class Body(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"error":{"code":"APPROVAL_OWNER_UNAVAILABLE"}}'

    async def aclose(self) -> None:
        pass


async def main() -> None:
    requests: list[httpx.Request] = []

    async def owner(request: httpx.Request) -> httpx.Response:
        await request.aread()
        requests.append(request)
        return httpx.Response(
            503,
            headers=[
                ("content-type", "application/json"),
                ("cache-control", "no-store"),
                ("retry-after", "2"),
                ("connection", "X-Internal-Hop, keep-alive"),
                ("x-internal-hop", "transport-only-fixture"),
                ("set-cookie", "fixture_one=; Path=/; Secure; HttpOnly; Max-Age=0"),
                ("set-cookie", "fixture_two=; Path=/; Secure; HttpOnly; Max-Age=0"),
            ],
            stream=Body(),
        )

    app = build_app()
    gateway = next(
        r.endpoint.__self__ for r in app.routes if getattr(r, "path", "") == "/api/{path:path}"
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(owner)) as upstream,
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client,
    ):
        gateway._client = upstream
        path = f"/api/v1/agent-sessions/{SESSION}/revoke"
        body = ('{"project_uuid":"' + PROJECT + '","expected_grant_revision":7}').encode()
        headers = {
            "origin": ORIGIN,
            "content-type": "application/json",
            "operation-uuid": OPERATION,
            "idempotency-key": OPERATION,
            "cookie": "opaque_fixture=not_a_verified_user",
            "x-forwarded-user": "forged",
        }
        for _ in range(2):
            response = await client.post(path, content=body, headers=headers)
            assert response.status_code == 503
            assert response.json() == {"error": {"code": "APPROVAL_OWNER_UNAVAILABLE"}}
            assert response.headers["retry-after"] == "2"
            assert len(response.headers.get_list("set-cookie")) == 2
            assert "x-internal-hop" not in response.headers, (
                "upstream Connection-nominated field leaked"
            )
            assert "connection" not in response.headers
            forwarded = requests[-1]
            assert forwarded.url.host == "briareus-control-panel-api"
            assert forwarded.headers["operation-uuid"] == OPERATION
            assert forwarded.headers["idempotency-key"] == OPERATION
            assert forwarded.headers["cookie"] == headers["cookie"]
            assert forwarded.content == body
            assert forwarded.headers["content-length"] == str(len(body))
            assert "x-forwarded-user" not in forwarded.headers
        assert requests[0].content == requests[1].content
        detail = f"/api/v1/agent-sessions/{SESSION}?project_uuid={PROJECT}"
        await client.get(detail, headers={"origin": ORIGIN})
        assert requests[-1].url.query.decode() == f"project_uuid={PROJECT}"
        before = len(requests)
        denied = await client.post(
            path, content=body, headers={**headers, "origin": "https://foreign.invalid"}
        )
        assert denied.status_code == 403 and len(requests) == before
        gateway._client = None
    print("MANAGEMENT_REPLAY_HEADERS_BODY_DETAIL_QUERY_FIDELITY_PASS")
    print("UPSTREAM_HOP_FIELDS_REMOVED_COOKIES_RETRY_AFTER_PRESERVED_PASS")
    print("NOT_PROVEN: authenticated approval or revoke")


if __name__ == "__main__":
    asyncio.run(main())
