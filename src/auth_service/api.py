from __future__ import annotations

import hmac

from fastmcp.server.auth import AccessToken
from pydantic import BaseModel, ConfigDict
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from common.settings import AuthServiceSettings

from .provider import MultiResourceGitHubProvider


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    token: str
    resource: str


def _service_authorized(request: Request, service_token: str) -> bool:
    authorization = request.headers.get("authorization", "")
    scheme, separator, value = authorization.partition(" ")
    return (
        separator == " "
        and scheme.casefold() == "bearer"
        and bool(service_token)
        and hmac.compare_digest(value, service_token)
    )


def build_auth_app(
    provider: MultiResourceGitHubProvider,
    settings: AuthServiceSettings,
) -> Starlette:
    async def health(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def verify(request: Request) -> Response:
        if not _service_authorized(request, settings.service_token):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)

        try:
            payload = VerifyRequest.model_validate(await request.json())
            expected_resource = provider.canonical_resource(payload.resource)
        except (ValueError, TypeError):
            return JSONResponse({"detail": "invalid verify request"}, status_code=400)

        token: AccessToken | None = await provider.load_access_token(payload.token)
        if token is None or token.resource != expected_resource:
            return JSONResponse({"detail": "invalid token"}, status_code=401)

        claims = token.claims or {}
        login = str(claims.get("login", "")).casefold()
        if not login or login not in settings.oauth_allowed_users:
            return JSONResponse({"detail": "user not allowed"}, status_code=403)

        return JSONResponse(token.model_dump(mode="json"))

    routes = list(provider.get_routes(mcp_path="/mcp"))
    routes.extend(
        [
            Route("/health", health, methods=["GET"]),
            Route("/internal/verify", verify, methods=["POST"]),
        ]
    )
    return Starlette(routes=routes)
