from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from common.models import JsonObject
from common.settings import ManagementSettings

_SESSION_KEY = "management_admin"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str


def build_admin_api_router(settings: ManagementSettings) -> APIRouter:
    router = APIRouter(prefix="/admin/api", tags=["admin"])

    def authenticated_username(request: Request) -> str | None:
        username = request.session.get(_SESSION_KEY)
        if not isinstance(username, str) or not username:
            return None
        if not hmac.compare_digest(username, settings.admin_username):
            request.session.clear()
            return None
        return username

    def require_user(request: Request) -> str:
        username = authenticated_username(request)
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
        return username

    def same_origin(request: Request) -> None:
        origin = request.headers.get("origin", "")
        if not origin:
            return
        public_host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        if urlsplit(origin).netloc.casefold() != public_host.casefold():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="origin rejected")

    @router.get("/session")
    def session_state(request: Request) -> JsonObject:
        username = authenticated_username(request)
        return {"authenticated": username is not None, "username": username}

    @router.post("/login")
    def login(payload: LoginRequest, request: Request) -> JsonObject:
        same_origin(request)
        valid_user = hmac.compare_digest(payload.username, settings.admin_username)
        valid_password = hmac.compare_digest(payload.password, settings.admin_password)
        if not (valid_user and valid_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid credentials",
            )
        request.session[_SESSION_KEY] = settings.admin_username
        return {"authenticated": True, "username": settings.admin_username}

    @router.post("/logout")
    def logout(request: Request) -> JsonObject:
        same_origin(request)
        request.session.clear()
        return {"authenticated": False, "username": None}

    @router.get("/bootstrap")
    def bootstrap(request: Request) -> JsonObject:
        require_user(request)
        return {
            "product": "MCP Management",
            "environment": "runtime",
            "legacy_admin_path": "/admin/",
            "navigation": [
                {"id": "overview", "label": "Overview", "enabled": True},
                {"id": "accounts", "label": "Accounts", "enabled": True},
                {"id": "calls", "label": "MCP Calls", "enabled": True},
                {"id": "files", "label": "Files", "enabled": True},
                {"id": "terminal", "label": "Terminal", "enabled": True},
                {"id": "browser", "label": "Browser", "enabled": True},
                {"id": "analysis", "label": "Analysis", "enabled": True},
                {"id": "oauth", "label": "OAuth Sessions", "enabled": True},
                {"id": "settings", "label": "Settings", "enabled": True},
            ],
        }

    return router
