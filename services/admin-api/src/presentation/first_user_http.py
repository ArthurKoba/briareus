"""First-user REST boundary: Admin owns /api, Identity owns credentials.

No Gateway-specific caller or service identity header is trusted. The single
fixed private upstream is deliberately independent of inbound Host and paths.
These four endpoints never grant access to other private owner operations.
"""

from __future__ import annotations

import json
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from identity_http_contracts import (
    AuthenticatedFirstUser,
    FirstUserLoginReceipt,
    FirstUserRegistrationReceipt,
)
from pydantic import BaseModel, ValidationError

from common.owner_bff_models import VerifiedAdminCaller

_ORIGIN = "https://briareus.koba-nexus.ru"
_MAX_REQUEST_BYTES = 16384
_MAX_RESPONSE_BYTES = 32768
_IDENTITY_ROUTES = {
    "register": "/internal/v1/identity/register",
    "login": "/internal/v1/identity/login",
    "logout": "/internal/v1/identity/logout",
}
_SAFE_FAILURES = frozenset({401, 403, 422, 429, 503})
_NOSTORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_INTERNAL_ERROR = {"error": {"code": "OWNER_SOURCE_UNAVAILABLE"}}


def _fail(status: int = 503) -> JSONResponse:
    if status == 401:
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "AUTHENTICATION_REQUIRED"}},
            headers=_NOSTORE,
        )
    return JSONResponse(
        status_code=status,
        content=_INTERNAL_ERROR if status == 503 else {"error": {"code": "REQUEST_REJECTED"}},
        headers=_NOSTORE,
    )


def _validate_browser(request: Request) -> None:
    if request.headers.get("cookie") is not None:
        raise HTTPException(401, detail="bearer-only first User API")
    if request.headers.get("origin") not in (None, _ORIGIN):
        raise HTTPException(403, detail="untrusted browser origin")
    if any(
        name.startswith(("x-forwarded-", "x-user-", "x-service-", "x-identity-"))
        or name in {"forwarded", "proxy-authorization", "x-original-url", "x-rewrite-url"}
        for name in request.headers
    ):
        raise HTTPException(403, detail="untrusted internal identity headers")


def _original(request: Request) -> str:
    raw = request.headers.get("operation-uuid", "")
    key = request.headers.get("idempotency-key", "")
    try:
        operation = UUID(raw)
    except (ValueError, AttributeError):
        raise HTTPException(422, detail="canonical original operation required") from None
    if operation.version != 4 or raw != str(operation) or key != raw:
        raise HTTPException(422, detail="canonical original operation mismatch")
    return raw


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if (
        not auth.startswith("Bearer ")
        or auth.count(" ") != 1
        or not 40 <= len(auth[7:]) <= 8192
        or any(ch.isspace() for ch in auth[7:])
    ):
        raise HTTPException(401, detail="signed bearer required")
    return auth


async def _private_request(
    request: Request,
    *,
    path: str,
    method: str,
    payload: bytes | None,
    bearer: str | None = None,
    original: str | None = None,
) -> httpx.Response | None:
    client: httpx.AsyncClient | None = getattr(request.app.state, "identity_client", None)
    if client is None:
        return None
    headers: dict[str, str] = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if bearer is not None:
        headers["Authorization"] = bearer
    if original is not None:
        headers["Operation-UUID"] = original
        headers["Idempotency-Key"] = original
    try:
        # Fixed internal path; no caller-controlled URL, redirect or cookie.
        return await client.request(
            method, path, headers=headers, content=payload, follow_redirects=False
        )
    except (httpx.HTTPError, TimeoutError):
        return None


async def _bounded_request(request: Request) -> bytes:
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise HTTPException(415, detail="JSON required")
    result = bytearray()
    async for chunk in request.stream():
        if len(result) + len(chunk) > _MAX_REQUEST_BYTES:
            raise HTTPException(413, detail="request exceeds first User API bound")
        result.extend(chunk)
    try:
        source = json.loads(result)
        if not isinstance(source, dict):
            raise ValueError("object required")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise HTTPException(422, detail="invalid JSON object") from None
    return bytes(result)


def _upstream_payload[T: BaseModel](response: httpx.Response, model: type[T]) -> T | None:
    if (
        response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json"
        or len(response.content) > _MAX_RESPONSE_BYTES
    ):
        return None
    try:
        return model.model_validate_json(response.content)
    except (ValidationError, ValueError):
        return None


def create_first_user_api_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["first-user"])

    @router.post("/auth/register", status_code=201)
    async def register(request: Request) -> Response:
        _validate_browser(request)
        operation = _original(request)
        data = await _bounded_request(request)
        result = await _private_request(
            request,
            path=_IDENTITY_ROUTES["register"],
            method="POST",
            payload=data,
            original=operation,
        )
        if result is None:
            return _fail()
        if result.status_code != 201:
            return _fail(result.status_code if result.status_code in _SAFE_FAILURES else 503)
        receipt = _upstream_payload(result, FirstUserRegistrationReceipt)
        if receipt is None:
            return _fail()
        return JSONResponse(
            status_code=201, content=receipt.model_dump(mode="json"), headers=_NOSTORE
        )

    @router.post("/auth/login")
    async def login(request: Request) -> Response:
        _validate_browser(request)
        operation = _original(request)
        data = await _bounded_request(request)
        result = await _private_request(
            request,
            path=_IDENTITY_ROUTES["login"],
            method="POST",
            payload=data,
            original=operation,
        )
        if result is None:
            return _fail()
        if result.status_code != 200:
            return _fail(result.status_code if result.status_code in _SAFE_FAILURES else 503)
        receipt = _upstream_payload(result, FirstUserLoginReceipt)
        if receipt is None:
            return _fail()
        return JSONResponse(
            status_code=200, content=receipt.model_dump(mode="json"), headers=_NOSTORE
        )

    @router.post("/auth/logout")
    async def logout(request: Request) -> Response:
        _validate_browser(request)
        operation = _original(request)
        bearer = _bearer(request)
        result = await _private_request(
            request,
            path=_IDENTITY_ROUTES["logout"],
            method="POST",
            payload=None,
            bearer=bearer,
            original=operation,
        )
        if result is None:
            return _fail()
        if result.status_code != 204:
            return _fail(result.status_code if result.status_code in _SAFE_FAILURES else 503)
        return Response(status_code=204, headers=_NOSTORE)

    @router.get("/platform/me", response_model=AuthenticatedFirstUser)
    async def current(request: Request) -> Response:
        _validate_browser(request)
        bearer = _bearer(request)
        result = await _private_request(
            request,
            path="/internal/v1/identity/current",
            method="POST",
            payload=None,
            bearer=bearer,
        )
        if result is None:
            return _fail()
        if result.status_code != 200:
            return _fail(result.status_code if result.status_code in _SAFE_FAILURES else 503)
        caller = _upstream_payload(result, VerifiedAdminCaller)
        if caller is None:
            return _fail()
        return JSONResponse(
            status_code=200, content=caller.model_dump(mode="json"), headers=_NOSTORE
        )

    return router
