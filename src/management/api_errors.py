from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse


def api_error(status_code: int, message: object) -> JSONResponse:
    code = {
        400: "invalid_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        502: "provider_unavailable",
        503: "service_unavailable",
        504: "timeout",
    }.get(status_code, "http_error")
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "version": 1,
                "code": code,
                "message": str(message),
                "status": status_code,
            }
        },
    )


def install_admin_api_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def admin_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        if request.url.path.startswith("/admin/api/"):
            return api_error(exc.status_code, exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def admin_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        if request.url.path.startswith("/admin/api/"):
            return api_error(422, exc.errors())
        return JSONResponse(status_code=422, content={"detail": exc.errors()})
