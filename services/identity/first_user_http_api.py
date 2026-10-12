# ruff: noqa: B008  # FastAPI parses Header dependencies from defaults.
"""Identity-only routes invoked through the Admin API on the private network."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from common.owner_bff_models import VerifiedAdminCaller
from common.platform_errors import (
    AuthenticationRateLimited,
    Conflict,
    InvalidInput,
    InvalidInvitation,
)
from identity.direct_first_user import (
    DirectFirstUserIdentity,
    SignedIdentityDenied,
)

_NOSTORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class RegistrationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    invitation: SecretStr = Field(min_length=32, max_length=256)
    username: str = Field(min_length=3, max_length=128)
    password: SecretStr = Field(min_length=12, max_length=4096)


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=3, max_length=128)
    password: SecretStr = Field(min_length=12, max_length=4096)


class FirstUserRegistrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    user_id: UUID
    role: str


class FirstUserLoginResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime


def _source(request: Request) -> DirectFirstUserIdentity:
    result: DirectFirstUserIdentity | None = getattr(request.app.state, "first_user", None)
    if not isinstance(result, DirectFirstUserIdentity):
        raise HTTPException(503, detail="Identity first-user owner unavailable")
    return result


def _admit(request: Request, *, preauth: bool = False) -> None:
    if request.headers.get("cookie") is not None:
        raise HTTPException(401, detail="bearer-only Identity authentication")
    if any(
        name.startswith(("x-user-", "x-service-", "x-identity-", "x-forwarded-"))
        or name in {"forwarded", "proxy-authorization", "x-original-url", "x-rewrite-url"}
        for name in request.headers
    ):
        raise HTTPException(403, detail="untrusted identity header")
    if preauth and request.headers.get("authorization"):
        raise HTTPException(401, detail="initial admission has no user bearer")


def _operation(operation: UUID, key: str) -> None:
    if operation.version != 4 or key != str(operation):
        raise HTTPException(422, detail="original operation UUID mismatch")


def _bearer(request: Request) -> str:
    token = request.headers.get("authorization", "")
    if (
        not token.startswith("Bearer ")
        or token.count(" ") != 1
        or not 40 <= len(token[7:]) <= 8192
        or any(char.isspace() for char in token[7:])
    ):
        raise HTTPException(401, detail="current signed bearer required")
    return token[7:]


def _error(status: int, code: str, *, unknown: bool = False) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "originalOutcomeUnknown": unknown}},
        headers=_NOSTORE,
    )


def build_first_user_http_api() -> APIRouter:
    router = APIRouter(prefix="/internal/v1/identity", tags=["first-user-http"])

    @router.post("/register", status_code=201, response_model=FirstUserRegistrationResult)
    async def register(
        request: Request,
        payload: RegistrationBody,
        operation_uuid: UUID = Header(alias="Operation-UUID"),
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> Response:
        _admit(request, preauth=True)
        _operation(operation_uuid, idempotency_key)
        owner = _source(request)
        try:
            user = await owner.register(
                payload.invitation.get_secret_value(),
                payload.username,
                payload.password.get_secret_value(),
            )
        except (InvalidInvitation, Conflict):
            return _error(403, "INVITATION_REJECTED")
        except InvalidInput:
            return _error(422, "REQUEST_REJECTED")
        except Exception:
            return _error(503, "OWNER_SOURCE_UNAVAILABLE", unknown=True)
        return JSONResponse(
            status_code=201,
            content={"user_id": str(user.id), "role": user.role.value},
            headers=_NOSTORE,
        )

    @router.post("/login", response_model=FirstUserLoginResult)
    async def login(
        request: Request,
        payload: LoginBody,
        operation_uuid: UUID = Header(alias="Operation-UUID"),
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> Response:
        _admit(request, preauth=True)
        _operation(operation_uuid, idempotency_key)
        owner = _source(request)
        try:
            signed, expires = await owner.login(
                username=payload.username,
                password=payload.password.get_secret_value(),
                source=request.client.host if request.client is not None else "private-http",
                operation=operation_uuid,
            )
        except AuthenticationRateLimited:
            return _error(429, "AUTHENTICATION_RATE_LIMITED")
        except SignedIdentityDenied:
            return _error(401, "AUTHENTICATION_REQUIRED")
        except Exception:
            return _error(503, "OWNER_SOURCE_UNAVAILABLE", unknown=True)
        return JSONResponse(
            status_code=200,
            content={
                "access_token": signed,
                "token_type": "Bearer",
                "expires_at": expires.isoformat(),
            },
            headers=_NOSTORE,
        )

    @router.post("/current", response_model=VerifiedAdminCaller)
    async def current(request: Request) -> Response:
        _admit(request)
        bearer = _bearer(request)
        try:
            user = await _source(request).current(bearer)
        except SignedIdentityDenied:
            return _error(401, "AUTHENTICATION_REQUIRED")
        except Exception:
            return _error(503, "OWNER_SOURCE_UNAVAILABLE")
        return JSONResponse(status_code=200, content=user.model_dump(mode="json"), headers=_NOSTORE)

    @router.post("/logout", status_code=204)
    async def logout(
        request: Request,
        operation_uuid: UUID = Header(alias="Operation-UUID"),
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> Response:
        _admit(request)
        _operation(operation_uuid, idempotency_key)
        bearer = _bearer(request)
        try:
            await _source(request).logout(bearer)
        except SignedIdentityDenied:
            return _error(401, "AUTHENTICATION_REQUIRED")
        except Exception:
            return _error(503, "OWNER_SOURCE_UNAVAILABLE", unknown=True)
        return Response(status_code=204, headers=_NOSTORE)

    return router
