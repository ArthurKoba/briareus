from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .provider import MultiResourceGitHubProvider


def build_auth_app(provider: MultiResourceGitHubProvider) -> Starlette:
    async def health(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    routes = list(provider.get_routes(mcp_path="/mcp"))
    routes.append(Route("/health", health, methods=["GET"]))
    return Starlette(routes=routes)
