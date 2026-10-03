from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

from bridge.reverse_proxy import ReverseProxy


def test_reverse_proxy_is_registered_as_request_handler() -> None:
    proxy = ReverseProxy("http://management:8000", backend_name="management")
    app = Starlette(routes=[Route("/admin", proxy.handle, methods=["GET"])])

    route = app.routes[0]
    assert isinstance(route, Route)
    assert route.endpoint == proxy.handle


@pytest.mark.asyncio
async def test_reverse_proxy_rewrites_internal_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(
            self,
            exc_type: object,
            exc: object,
            traceback: object,
        ) -> None:
            return None

        async def request(self, *args: object, **kwargs: object) -> httpx.Response:
            request = httpx.Request("GET", "http://management:8000/admin")
            return httpx.Response(
                307,
                headers={"location": "http://management:8000/admin/"},
                request=request,
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    proxy = ReverseProxy("http://management:8000", backend_name="management")

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": "/admin",
            "raw_path": b"/admin",
            "query_string": b"",
            "headers": [(b"host", b"mcp.koba-nexus.ru")],
            "client": ("127.0.0.1", 1234),
            "server": ("mcp.koba-nexus.ru", 443),
            "http_version": "1.1",
        },
        receive=receive,
    )

    response = await proxy.handle(request)

    assert response.status_code == 307
    assert response.headers["location"] == "/admin/"


@pytest.mark.asyncio
async def test_reverse_proxy_rewrites_backend_origin_inside_next_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(
            self,
            exc_type: object,
            exc: object,
            traceback: object,
        ) -> None:
            return None

        async def request(self, *args: object, **kwargs: object) -> httpx.Response:
            request = httpx.Request("GET", "http://management:8000/admin/")
            return httpx.Response(
                303,
                headers={
                    "location": (
                        "/admin/login?"
                        "next=http%3A%2F%2Fmanagement%3A8000%2Fadmin%2F"
                    )
                },
                request=request,
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    proxy = ReverseProxy("http://management:8000", backend_name="management")

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": "/admin/",
            "raw_path": b"/admin/",
            "query_string": b"",
            "headers": [(b"host", b"mcp.koba-nexus.ru")],
            "client": ("127.0.0.1", 1234),
            "server": ("mcp.koba-nexus.ru", 443),
            "http_version": "1.1",
        },
        receive=receive,
    )

    response = await proxy.handle(request)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login?next=%2Fadmin%2F"


@pytest.mark.asyncio
async def test_reverse_proxy_forwards_public_origin_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class FakeClient:
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(
            self,
            exc_type: object,
            exc: object,
            traceback: object,
        ) -> None:
            return None

        async def request(self, *args: object, **kwargs: object) -> httpx.Response:
            headers = kwargs["headers"]
            assert isinstance(headers, dict)
            captured.update(headers)
            request = httpx.Request("GET", "http://management:8000/admin/")
            return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    proxy = ReverseProxy("http://management:8000", backend_name="management")

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/admin/",
            "raw_path": b"/admin/",
            "query_string": b"",
            "headers": [
                (b"host", b"mcp.koba-nexus.ru"),
                (b"x-forwarded-host", b"spoofed.invalid"),
                (b"x-forwarded-proto", b"https"),
            ],
            "client": ("127.0.0.1", 1234),
            "server": ("mcp.koba-nexus.ru", 443),
            "http_version": "1.1",
        },
        receive=receive,
    )

    response = await proxy.handle(request)

    assert response.status_code == 200
    assert captured["host"] == "mcp.koba-nexus.ru"
    assert captured["x-forwarded-host"] == "mcp.koba-nexus.ru"
    assert captured["x-forwarded-proto"] == "https"


@pytest.mark.asyncio
async def test_reverse_proxy_reuses_one_http_client_across_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"clients": 0, "requests": 0, "closed": 0}

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            state["clients"] += 1

        async def request(self, *args: object, **kwargs: object) -> httpx.Response:
            del args, kwargs
            state["requests"] += 1
            request = httpx.Request("GET", "http://management:8000/admin")
            return httpx.Response(200, request=request)

        async def aclose(self) -> None:
            state["closed"] += 1

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    proxy = ReverseProxy("http://management:8000", backend_name="management")

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "GET",
        "scheme": "https",
        "path": "/admin",
        "raw_path": b"/admin",
        "query_string": b"",
        "headers": [(b"host", b"mcp.koba-nexus.ru")],
        "client": ("127.0.0.1", 1234),
        "server": ("mcp.koba-nexus.ru", 443),
        "http_version": "1.1",
    }

    assert (await proxy.handle(Request(scope, receive=receive))).status_code == 200
    assert (await proxy.handle(Request(scope, receive=receive))).status_code == 200
    await proxy.close()

    assert state == {"clients": 1, "requests": 2, "closed": 1}


@pytest.mark.asyncio
async def test_reverse_proxy_streams_event_source_without_buffering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"sent_stream": False, "closed": 0}

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def build_request(
            self,
            method: str,
            url: str,
            **kwargs: object,
        ) -> httpx.Request:
            return httpx.Request(method, url, headers=kwargs.get("headers"))

        async def send(
            self,
            request: httpx.Request,
            *,
            stream: bool = False,
        ) -> httpx.Response:
            state["sent_stream"] = stream

            async def body():
                yield b"data: {\"status\":\"ok\"}\\n\\n"

            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=httpx.ByteStream(b"data: {\"status\":\"ok\"}\\n\\n"),
                request=request,
            )

        async def aclose(self) -> None:
            state["closed"] += 1

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    proxy = ReverseProxy("http://management:8000", backend_name="management")

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": "/admin/api/calls/stream",
            "raw_path": b"/admin/api/calls/stream",
            "query_string": b"",
            "headers": [
                (b"host", b"mcp.koba-nexus.ru"),
                (b"accept", b"text/event-stream"),
            ],
            "client": ("127.0.0.1", 1234),
            "server": ("mcp.koba-nexus.ru", 443),
            "http_version": "1.1",
        },
        receive=receive,
    )

    response = await proxy.handle(request)

    assert isinstance(response, StreamingResponse)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert state["sent_stream"] is True
