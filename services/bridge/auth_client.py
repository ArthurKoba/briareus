from __future__ import annotations

from fastmcp.server.auth import AccessToken, TokenVerifier

from common.mcp_surfaces import canonical_public_base_url
from common.oauth_tokens import load_oauth_public_key, verify_oauth_access_token
from common.settings import GatewayAuthSettings


class LocalAuthTokenVerifier(TokenVerifier):
    """Validate locally issued OAuth access tokens without calling auth per request."""

    def __init__(self, settings: GatewayAuthSettings, resource: str) -> None:
        super().__init__(required_scopes=["read:user"])
        self.resource = resource
        self.issuer = canonical_public_base_url(settings.public_base_url)
        self._public_key = load_oauth_public_key(settings.jwt_public_key_pem)

    async def verify_token(self, token: str) -> AccessToken | None:
        payload = verify_oauth_access_token(
            token,
            public_key=self._public_key,
            issuer=self.issuer,
            audience=self.resource,
        )
        if payload is None:
            return None

        scope = payload.get("scope")
        scopes = scope.split() if isinstance(scope, str) and scope else []
        if not set(self.required_scopes).issubset(scopes):
            return None

        client_id = str(payload.get("client_id") or "")
        subject = str(payload.get("sub") or "")
        if not client_id or not subject:
            return None

        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(payload["exp"]),
            subject=subject,
            resource=self.resource,
            claims=payload,
        )
