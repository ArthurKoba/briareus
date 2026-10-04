from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import UTC, datetime

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.jwt_issuer import JWTIssuer, derive_jwt_key
from pydantic import AnyHttpUrl

from common.admin_api_client import AdminApiClient
from common.oauth_session_contracts import OAuthSessionEvent
from common.settings import GatewayAuthSettings


class LocalAuthTokenVerifier(TokenVerifier):
    """Validate FastMCP access tokens locally without calling the auth runtime."""

    def __init__(
        self,
        settings: GatewayAuthSettings,
        resource: str,
        admin_api: AdminApiClient | None = None,
    ) -> None:
        super().__init__(required_scopes=["read:user"])
        self.resource = resource
        self.allowed_users = frozenset(settings.oauth_allowed_users)
        self.admin_api = admin_api
        self._touches: dict[str, float] = {}
        signing_key = derive_jwt_key(
            low_entropy_material=settings.oauth_jwt_signing_key,
            salt="fastmcp-jwt-signing-key",
        )
        self._issuer = JWTIssuer(
            issuer=str(AnyHttpUrl(settings.public_base_url)),
            audience=resource,
            signing_key=signing_key,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            payload = self._issuer.verify_token(token)
        except Exception:
            return None

        upstream_claims = payload.get("upstream_claims")
        if not isinstance(upstream_claims, dict):
            return None

        login = str(upstream_claims.get("login", "")).casefold()
        if not login or login not in self.allowed_users:
            return None

        scope = payload.get("scope", "")
        scopes = scope.split() if isinstance(scope, str) and scope else []
        required = set(self.required_scopes)
        if not required.issubset(scopes):
            return None

        client_id = str(payload.get("client_id", ""))
        jti = str(payload.get("jti", ""))
        now = time.monotonic()
        touch_key = f"{client_id}\0{self.resource}\0{login}\0{jti}"
        previous_touch = self._touches.get(touch_key)
        if self.admin_api is not None and (previous_touch is None or now - previous_touch >= 60.0):
            self._touches[touch_key] = now
            with contextlib.suppress(Exception):
                await asyncio.to_thread(
                    self.admin_api.record_oauth_session,
                    OAuthSessionEvent(
                        client_id=client_id,
                        resource=self.resource,
                        login=login,
                        subject=str(upstream_claims.get("sub") or ""),
                        scopes=scopes,
                        status="active",
                        event="access_used",
                        access_jti=jti,
                        access_expires_at=(
                            None
                            if payload.get("exp") is None
                            else datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
                        ),
                    ),
                )

        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(payload["exp"]) if payload.get("exp") is not None else None,
            subject=str(upstream_claims.get("sub") or "") or None,
            resource=self.resource,
            claims=payload,
        )
