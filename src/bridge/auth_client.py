from __future__ import annotations

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.jwt_issuer import JWTIssuer, derive_jwt_key
from pydantic import AnyHttpUrl

from common.settings import GatewayAuthSettings


class LocalAuthTokenVerifier(TokenVerifier):
    """Validate FastMCP access tokens locally without calling the auth runtime."""

    def __init__(self, settings: GatewayAuthSettings, resource: str) -> None:
        super().__init__(required_scopes=["read:user"])
        self.resource = resource
        self.allowed_users = frozenset(settings.oauth_allowed_users)
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

        return AccessToken(
            token=token,
            client_id=str(payload.get("client_id", "")),
            scopes=scopes,
            expires_at=int(payload["exp"]) if payload.get("exp") is not None else None,
            subject=str(upstream_claims.get("sub") or "") or None,
            resource=self.resource,
            claims=payload,
        )
