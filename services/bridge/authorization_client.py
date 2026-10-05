from __future__ import annotations

import asyncio
from time import monotonic

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastmcp.server.auth import AccessToken, TokenVerifier

from common.mcp_surfaces import canonical_public_base_url
from common.oauth_tokens import verify_oauth_access_token
from common.settings import GatewayAuthorizationSettings

_JWKS_CACHE_TTL_SECONDS = 300.0


class AuthorizationJwksClient:
    def __init__(
        self,
        settings: GatewayAuthorizationSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=settings.authorization_internal_url.rstrip("/"),
            timeout=2.0,
        )
        self._owns_client = client is None
        self._keys: dict[str, ec.EllipticCurvePublicKey] = {}
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def key_for_token(self, token: str) -> ec.EllipticCurvePublicKey | None:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            return None
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            return None

        now = monotonic()
        cached = self._keys.get(kid)
        if cached is not None and now < self._expires_at:
            return cached

        async with self._lock:
            now = monotonic()
            cached = self._keys.get(kid)
            if cached is not None and now < self._expires_at:
                return cached
            try:
                await self._refresh()
            except (httpx.HTTPError, ValueError, TypeError):
                # Already-fetched public keys remain usable if authorization is
                # temporarily unavailable; unknown keys still fail closed.
                return cached
            return self._keys.get(kid)

    async def _refresh(self) -> None:
        response = await self._client.get("/.well-known/jwks.json")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
            raise ValueError("authorization JWKS response is invalid")

        resolved: dict[str, ec.EllipticCurvePublicKey] = {}
        for value in payload["keys"]:
            if not isinstance(value, dict):
                continue
            kid = value.get("kid")
            if (
                not isinstance(kid, str)
                or not kid
                or value.get("kty") != "EC"
                or value.get("crv") != "P-256"
                or value.get("alg") not in {None, "ES256"}
            ):
                continue
            try:
                key = jwt.algorithms.ECAlgorithm.from_jwk(value)
            except (ValueError, TypeError):
                continue
            if isinstance(key, ec.EllipticCurvePublicKey) and isinstance(
                key.curve, ec.SECP256R1
            ):
                resolved[kid] = key
        if not resolved:
            raise ValueError("authorization JWKS contains no usable ES256 keys")
        self._keys = resolved
        self._expires_at = monotonic() + _JWKS_CACHE_TTL_SECONDS


class LocalAuthorizationTokenVerifier(TokenVerifier):
    """Validate locally issued OAuth access tokens with cached authorization JWKS."""

    def __init__(
        self,
        settings: GatewayAuthorizationSettings,
        resource: str,
        jwks: AuthorizationJwksClient,
    ) -> None:
        super().__init__(required_scopes=["read:user"])
        self.resource = resource
        self.issuer = canonical_public_base_url(settings.public_base_url)
        self._jwks = jwks

    async def verify_token(self, token: str) -> AccessToken | None:
        public_key = await self._jwks.key_for_token(token)
        if public_key is None:
            return None
        payload = verify_oauth_access_token(
            token,
            public_key=public_key,
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
