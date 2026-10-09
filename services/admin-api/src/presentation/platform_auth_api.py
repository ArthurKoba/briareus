# ruff: noqa: B008  # FastAPI security dependencies
"""Local Admin bearer routes, unmounted until C1-B/C2 security approval."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from authorization._platform_auth import PlatformAdminBearerAuth
from common.platform_errors import AuthenticationRequired


class LocalAdminLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=4096)


class LocalAdminToken(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime


def build_unmounted_platform_auth_router(auth: PlatformAdminBearerAuth) -> APIRouter:
    router = APIRouter(tags=["platform-auth-draft"])
    bearer_schema = HTTPBearer(auto_error=False, scheme_name="PlatformAdminBearer")

    @router.post("/auth/login", response_model=LocalAdminToken)
    async def local_login(
        payload: LocalAdminLogin,
        request: Request,
        response: Response,
    ) -> LocalAdminToken:
        # Network TLS + trusted proxy + distributed login source requirements
        # must be verified by C2 BEFORE this path is mounted.
        if request.client is None or not request.client.host:
            raise AuthenticationRequired("verified network source required")
        issued = await auth.authenticate_local(
            payload.username,
            payload.password.get_secret_value(),
            source=request.client.host,
        )
        if issued is None:
            raise AuthenticationRequired("invalid credentials")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return LocalAdminToken(
            access_token=issued.secret.get_secret_value(),
            expires_at=issued.expires_at,
        )

    @router.post("/auth/logout")
    async def local_logout(
        request: Request,
        response: Response,
        _credentials: HTTPAuthorizationCredentials | None = Depends(bearer_schema),
    ) -> dict[str, bool]:
        caller = await auth.resolve(request)
        if caller is None:
            raise AuthenticationRequired("invalid Admin credential")
        header = request.headers.get("authorization", "")
        parts = header.split(" ")
        if len(parts) != 2:
            raise AuthenticationRequired("invalid Admin credential")
        await auth.revoke(parts[1], caller=caller)
        response.headers["Cache-Control"] = "no-store"
        return {"revoked": True}

    @router.post("/auth/refresh", response_model=LocalAdminToken)
    async def local_refresh(
        request: Request,
        response: Response,
        _credentials: HTTPAuthorizationCredentials | None = Depends(bearer_schema),
    ) -> LocalAdminToken:
        caller = await auth.resolve(request)
        if caller is None:
            raise AuthenticationRequired("invalid Admin credential")
        header = request.headers.get("authorization", "")
        parts = header.split(" ")
        if len(parts) != 2:
            raise AuthenticationRequired("invalid Admin credential")
        issued = await auth.rotate(parts[1], caller=caller)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return LocalAdminToken(
            access_token=issued.secret.get_secret_value(),
            expires_at=issued.expires_at,
        )

    return router
