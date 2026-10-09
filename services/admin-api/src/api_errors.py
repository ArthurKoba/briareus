from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

from common.platform_errors import PlatformError


def api_error(
    status_code: int, message: object, *, semantic_code: str | None = None
) -> JSONResponse:
    code = {
        400: "invalid_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        502: "provider_unavailable",
        503: "service_unavailable",
        500: "internal_error",
        504: "timeout",
    }.get(status_code, "http_error")
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "version": 1,
                "code": semantic_code or code,
                "message": str(message),
                "status": status_code,
            }
        },
    )


def _safe_validation_details(exc: RequestValidationError) -> list[dict[str, object]]:
    """Strip Pydantic input/context: they may contain passwords/credentials."""
    details: list[dict[str, object]] = []
    for error in exc.errors()[:32]:
        raw_loc = error.get("loc", ())
        safe_loc: list[str | int] = []
        for entry in raw_loc[:8]:
            safe_name = (
                isinstance(entry, str)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", entry)
            )
            if isinstance(entry, int) or safe_name:
                safe_loc.append(entry)
            else:
                safe_loc.append("field")
        details.append(
            {
                "loc": safe_loc,
                "type": str(error.get("type", "invalid"))[:64],
                "message": "Invalid request value",
            }
        )
    return details


def install_admin_api_error_handlers(app: FastAPI) -> None:

    @app.exception_handler(PlatformError)
    async def platform_domain_error(_request: Request, exc: PlatformError) -> JSONResponse:
        return api_error(exc.status_code, str(exc), semantic_code=exc.code)

    @app.exception_handler(StarletteHTTPException)
    async def admin_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if request.url.path.startswith("/v1/"):
            return api_error(exc.status_code, exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def admin_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        if request.url.path.startswith("/v1/"):
            return api_error(422, _safe_validation_details(exc))
        return JSONResponse(status_code=422, content={"detail": _safe_validation_details(exc)})

    @app.middleware("http")
    async def admin_internal_error_boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = uuid4().hex
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            if not request.url.path.startswith("/v1/"):
                raise
            response = api_error(500, "internal server error")
        if request.url.path.startswith("/v1/"):
            response.headers["X-Request-ID"] = request_id
        return response
