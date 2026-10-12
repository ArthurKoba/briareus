"""Briareus Admin health shell; owner-signed BFF is not publicly activated.

No cross-owner SQLAlchemy session or old global schema readiness is allowed.
The real BFF must use independently verified Identity/Access/Control/Catalog
source-owner API ports after reviewer acceptance of C1-B2/C2.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
from fastapi import FastAPI
from presentation.first_user_http import create_first_user_api_router

if TYPE_CHECKING:
    from presentation.private_c2_api import PrivateFirstUserApiPorts, PrivateOwnerApiPorts


def create_platform_admin_app(services: object | None = None) -> FastAPI:
    if services is not None:
        raise RuntimeError("global PlatformServices BFF rejected: owner service ports required")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            base_url="http://briareus-identity:8000",
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(5, connect=2),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        ) as client:
            app.state.identity_client = client
            try:
                yield
            finally:
                app.state.identity_client = None

    app = FastAPI(
        lifespan=lifespan,
        title="Briareus Administration",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health/live", include_in_schema=False)
    async def live() -> dict[str, str]:
        return {"state": "live", "api": "first-user-http", "authorization": "identity-owned"}

    app.include_router(create_first_user_api_router())
    return app


app = create_platform_admin_app()


def create_trusted_private_platform_app(ports: PrivateOwnerApiPorts) -> FastAPI:
    """Private C2-injected Admin API, never the default published app.

    Physical release approval, current owner peers and per-request identity
    must be independently supplied. No header/ENV can self-install C2.
    """
    if ports is None:
        raise RuntimeError("trusted private Admin API requires injected C2 source")
    from presentation.private_c2_api import create_unmounted_private_owner_api

    return create_unmounted_private_owner_api(ports)


def create_trusted_first_user_admin_app(ports: PrivateFirstUserApiPorts) -> FastAPI:
    """Minimal source-only /me, signed Identity without invented Project."""
    if ports is None:
        raise RuntimeError("first User Admin API requires trusted C2")
    from presentation.private_c2_api import create_unmounted_first_user_admin_app

    return create_unmounted_first_user_admin_app(ports)
