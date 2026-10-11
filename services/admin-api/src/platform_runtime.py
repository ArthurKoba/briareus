"""Briareus Admin health shell; owner-signed BFF is not publicly activated.

No cross-owner SQLAlchemy session or old global schema readiness is allowed.
The real BFF must use independently verified Identity/Access/Control/Catalog
source-owner API ports after reviewer acceptance of C1-B2/C2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from presentation.private_c2_api import PrivateOwnerApiPorts


def create_platform_admin_app(services: object | None = None) -> FastAPI:
    if services is not None:
        raise RuntimeError("global PlatformServices BFF rejected: owner service ports required")
    app = FastAPI(
        title="Briareus Administration",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health/live", include_in_schema=False)
    async def live() -> dict[str, str]:
        return {"state": "live", "api": "unmounted", "authorization": "not_attested"}

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
