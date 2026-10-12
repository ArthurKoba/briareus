"""Control Panel API: stable BFF boundary, independent from Identity lifecycle."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from ._oidc import OidcProviderUnavailable, RauthyOidcAdapter


class OidcBrowserConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer: str
    client_id: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None


def create_control_panel_api(*, provider: RauthyOidcAdapter | None = None) -> FastAPI:
    managed_provider = provider
    if managed_provider is None:
        issuer = os.environ.get("OIDC_ISSUER", "")
        client_id = os.environ.get("OIDC_CLIENT_ID", "")
        if issuer or client_id:
            if not issuer or not client_id:
                raise RuntimeError("both OIDC_ISSUER and OIDC_CLIENT_ID must be configured")
            managed_provider = RauthyOidcAdapter(issuer=issuer, client_id=client_id)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if managed_provider is not None:
                await managed_provider.close()

    app = FastAPI(
        title="Briareus Control Panel API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health/live", include_in_schema=False)
    async def live() -> dict[str, str]:
        return {"state": "live", "service": "control-panel-api"}

    @app.get("/api/auth/oidc/config", response_model=OidcBrowserConfiguration)
    async def oidc_config(response: Response) -> OidcBrowserConfiguration:
        response.headers["Cache-Control"] = "no-store"
        if managed_provider is None:
            raise HTTPException(status_code=503, detail="identity provider is not configured")
        try:
            configuration = await managed_provider.public_configuration()
        except OidcProviderUnavailable as exc:
            raise HTTPException(status_code=503, detail="identity provider unavailable") from exc
        return OidcBrowserConfiguration(**vars(configuration))

    return app


app = create_control_panel_api()
