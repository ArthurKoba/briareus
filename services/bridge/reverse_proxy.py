from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response, StreamingResponse

_TRACER = trace.get_tracer("mcp-bridge.reverse-proxy")

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


class ReverseProxy:
    def __init__(
        self,
        base_url: str,
        *,
        backend_name: str,
        public_prefix: str = "",
        upstream_prefix: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.backend_name = backend_name
        self.public_prefix = public_prefix.rstrip("/")
        self.upstream_prefix = upstream_prefix.rstrip("/")
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=30,
            limits=httpx.Limits(
                max_connections=32,
                max_keepalive_connections=16,
                keepalive_expiry=30,
            ),
        )

    async def close(self) -> None:
        await self._client.aclose()

    def _upstream_path(self, path: str) -> str:
        if not self.public_prefix:
            return path
        if path == self.public_prefix:
            suffix = ""
        elif path.startswith(self.public_prefix + "/"):
            suffix = path[len(self.public_prefix) :]
        else:
            raise ValueError(f"path {path!r} is outside public prefix {self.public_prefix!r}")
        if self.upstream_prefix:
            return self.upstream_prefix + suffix
        return suffix or "/"

    @staticmethod
    def _request_headers(request: Request) -> dict[str, str]:
        stripped = {
            "host",
            "content-length",
            "x-forwarded-host",
            "x-forwarded-proto",
        }
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.casefold() not in _HOP_BY_HOP | stripped
        }
        public_host = request.headers.get("host", "")
        headers["host"] = public_host
        headers["x-forwarded-host"] = public_host
        headers["x-forwarded-proto"] = request.headers.get(
            "x-forwarded-proto",
            request.url.scheme,
        )
        return headers

    def _without_backend_origin(self, value: str) -> str:
        backend = urlsplit(self.base_url)
        candidate = urlsplit(value)
        if (candidate.scheme, candidate.netloc) != (backend.scheme, backend.netloc):
            return value

        base_path = backend.path.rstrip("/")
        if base_path and not candidate.path.startswith(base_path + "/"):
            return value
        path = candidate.path[len(base_path) :] if base_path else candidate.path
        return urlunsplit(("", "", path or "/", candidate.query, candidate.fragment))

    def _rewrite_location(self, location: str) -> str:
        rewritten = self._without_backend_origin(location)
        parsed = urlsplit(rewritten)
        if not parsed.query:
            return rewritten

        query = parse_qsl(parsed.query, keep_blank_values=True)
        normalized = [(key, self._without_backend_origin(value)) for key, value in query]
        if normalized == query:
            return rewritten
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlencode(normalized),
                parsed.fragment,
            )
        )

    def _response_headers(self, headers: Mapping[str, str]) -> dict[str, str]:
        forwarded = {
            key: value
            for key, value in headers.items()
            if key.casefold() not in _HOP_BY_HOP | {"content-length"}
        }
        location = forwarded.get("location")
        if location is not None:
            forwarded["location"] = self._rewrite_location(location)
        return forwarded

    async def handle(self, request: Request) -> Response:
        target = self.base_url + self._upstream_path(request.url.path)
        if request.url.query:
            target += "?" + request.url.query
        with _TRACER.start_as_current_span(
            "gateway.reverse_proxy",
            kind=SpanKind.CLIENT,
            attributes={
                "mcp.backend": self.backend_name,
                "http.request.method": request.method,
            },
        ) as span:
            try:
                request_headers = self._request_headers(request)
                wants_stream = (
                    request.headers.get("accept", "").casefold().startswith("text/event-stream")
                )
                if wants_stream:
                    backend_request = self._client.build_request(
                        request.method,
                        target,
                        content=await request.body(),
                        headers=request_headers,
                    )
                    response = await self._client.send(backend_request, stream=True)
                else:
                    response = await self._client.request(
                        request.method,
                        target,
                        content=await request.body(),
                        headers=request_headers,
                    )
            except httpx.RequestError as exc:
                span.record_exception(exc)
                return PlainTextResponse(
                    f"{self.backend_name} backend unavailable",
                    status_code=502,
                )
            span.set_attribute("http.response.status_code", response.status_code)

        headers = self._response_headers(response.headers)
        if wants_stream:
            return StreamingResponse(
                response.aiter_raw(),
                status_code=response.status_code,
                headers=headers,
                media_type=None,
                background=BackgroundTask(response.aclose),
            )

        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=headers,
            media_type=None,
        )
