"""Control Panel API: stable BFF boundary, independent from Identity lifecycle."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, SecretStr

from ._legacy_identity import create_first_user_api_router
from ._oidc import OidcProviderUnavailable, RauthyOidcAdapter
from ._oidc_browser import OidcBrowserSessionStore, oidc_browser_router
from ._rauthy_admin import RauthyAdminClient, RauthyAdminKeyRejected


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

    # No browser cookie or User token can provision an admin API credential.
    raw_api_key = os.environ.get("RAUTHY_ADMIN_API_KEY", "")
    service_admin = None
    admin_key_state = "unconfigured"
    if raw_api_key:
        try:
            service_admin = RauthyAdminClient(api_key=SecretStr(raw_api_key))
            admin_key_state = "configured_unverified"
        except RauthyAdminKeyRejected:
            # Invalid optional integration must never crash the independent
            # Control Panel API. Only this integration remains disabled.
            admin_key_state = "invalid_credential"

    # Private, short-lived browser transactions/sessions, NOT platform grants.
    # The Valkey credential is owned by the existing External Services stack.
    raw_valkey_key = os.environ.get("OIDC_SESSION_VALKEY_PASSWORD", "")
    browser_sessions = None
    if raw_valkey_key:
        with suppress(ValueError):
            browser_sessions = OidcBrowserSessionStore(password=SecretStr(raw_valkey_key))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Preserve the existing /api/auth and /api/platform/me routes until
        # the Rauthy code+PKCE cutover is verified. Never import Identity ORM.
        async with httpx.AsyncClient(
            base_url="http://briareus-identity:8000",
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(5, connect=2),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        ) as identity_client:
            _app.state.identity_client = identity_client
            _app.state.rauthy_admin = service_admin
            _app.state.rauthy_admin_state = admin_key_state
            try:
                yield
            finally:
                _app.state.identity_client = None
                _app.state.rauthy_admin = None
                _app.state.rauthy_admin_state = None
                if service_admin is not None:
                    await service_admin.close()
                if browser_sessions is not None:
                    await browser_sessions.close()
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
        return {
            "state": "live",
            "service": "control-panel-api",
            "api": "first-user-http",
            "authorization": "identity-owned",
        }

    app.include_router(create_first_user_api_router())
    if managed_provider is not None and browser_sessions is not None:
        app.include_router(oidc_browser_router(managed_provider, browser_sessions))
    else:
        # Preserve a stable unconfigured API instead of a misleading 404.
        @app.get("/api/auth/oidc/start")
        async def oidc_start_unavailable() -> Response:
            raise HTTPException(503, detail="OIDC login is not configured")

        @app.get("/api/auth/oidc/callback")
        async def oidc_callback_unavailable() -> Response:
            raise HTTPException(503, detail="OIDC login is not configured")

        @app.get("/api/auth/oidc/session")
        async def oidc_session_unavailable() -> Response:
            raise HTTPException(503, detail="OIDC login is not configured")

        @app.post("/api/auth/oidc/logout")
        async def oidc_logout_unavailable() -> Response:
            raise HTTPException(503, detail="OIDC login is not configured")

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
