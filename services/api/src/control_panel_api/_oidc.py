"""Rauthy OpenID Connect discovery through standards, not private APIs.

This is an upstream Identity adapter, NOT an alternate issuer, password store,
or a grant authority. Public configuration may be forwarded to the browser;
privileged Rauthy Admin REST remains a separate, unexposed integration.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from urllib.parse import urlencode, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from ._oidc_id_token import VerifiedOidcIdentity, verify_rauthy_id_token


class OidcProviderUnavailable(Exception):
    """Issuer is unconfigured, unavailable, or returned untrusted metadata."""


class OidcDiscovery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None = None
    code_challenge_methods_supported: list[str] = Field(default_factory=list)
    response_types_supported: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PublicOidcConfiguration:
    issuer: str
    client_id: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None


@dataclass(frozen=True, slots=True)
class OidcAuthorizationAttempt:
    """Pending provider login, not authenticated User or Session proof."""

    authorization_url: str
    state: str
    nonce: str
    code_verifier: SecretStr
    redirect_uri: str
    expires_at: datetime


class UnverifiedOidcTokenResponse(BaseModel):
    """Upstream tokens: NOT a verified actor or platform permission."""

    model_config = ConfigDict(extra="ignore")

    access_token: SecretStr = Field(min_length=40)
    id_token: SecretStr = Field(min_length=40)
    token_type: str
    expires_in: int = Field(gt=0, le=86_400)


def _pkce_s256(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )


def _is_https_url(value: str) -> bool:
    try:
        url = urlsplit(value)
    except ValueError:
        return False
    return (
        url.scheme == "https"
        and bool(url.hostname)
        and url.username is None
        and url.password is None
        and not url.fragment
        and not url.query
    )


class RauthyOidcAdapter:
    """Fetch OIDC metadata once per bounded TTL; never proxy credentials."""

    def __init__(
        self,
        *,
        issuer: str,
        client_id: str,
        http_client: httpx.AsyncClient | None = None,
        cache_seconds: float = 300.0,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        if not _is_https_url(self._issuer) or not client_id or not client_id.strip():
            raise ValueError("OIDC requires a real HTTPS issuer and client ID")
        self._client = http_client or httpx.AsyncClient(timeout=5.0, follow_redirects=False)
        self._owns_client = http_client is None
        self._cache_seconds = max(1.0, cache_seconds)
        self._cached: OidcDiscovery | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def discovery(self) -> OidcDiscovery:
        if self._cached is not None and monotonic() < self._expires_at:
            return self._cached
        async with self._lock:
            if self._cached is not None and monotonic() < self._expires_at:
                return self._cached
            try:
                response = await self._client.get(
                    f"{self._issuer}/.well-known/openid-configuration",
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                metadata = OidcDiscovery.model_validate(response.json())
            except (httpx.HTTPError, ValidationError, ValueError, TypeError) as exc:
                raise OidcProviderUnavailable("OIDC issuer discovery unavailable") from exc
            endpoints = (
                metadata.authorization_endpoint,
                metadata.token_endpoint,
                metadata.jwks_uri,
            )
            if (
                metadata.issuer.rstrip("/") != self._issuer
                or any(not _is_https_url(url) for url in endpoints)
                or (
                    metadata.userinfo_endpoint is not None
                    and not _is_https_url(metadata.userinfo_endpoint)
                )
                or "code" not in metadata.response_types_supported
                or "S256" not in metadata.code_challenge_methods_supported
            ):
                raise OidcProviderUnavailable("OIDC issuer metadata violates secure PKCE contract")
            self._cached = metadata
            self._expires_at = monotonic() + self._cache_seconds
            return metadata

    async def prepare_authorization_code(self, *, redirect_uri: str) -> OidcAuthorizationAttempt:
        """Create an upstream code+PKCE request for a verified public client.

        A trusted BFF must store the verifier/state/nonce privately until a
        one-time callback. The redirect URI comes from approved config, never
        caller-controlled Host or query parameters.
        """
        if not _is_https_url(redirect_uri):
            raise ValueError("approved HTTPS OIDC callback required")
        provider = await self.discovery()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "scope": "openid profile email",
                "state": state,
                "nonce": nonce,
                "code_challenge": _pkce_s256(verifier),
                "code_challenge_method": "S256",
            }
        )
        return OidcAuthorizationAttempt(
            authorization_url=f"{provider.authorization_endpoint}?{query}",
            state=state,
            nonce=nonce,
            code_verifier=SecretStr(verifier),
            redirect_uri=redirect_uri,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )

    async def exchange_authorization_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: SecretStr,
    ) -> UnverifiedOidcTokenResponse:
        """Redeem code against verified Rauthy without making local JWTs.

        Trusted caller must atomically consume the matching one-time state
        before use. Returned tokens are not verified login or access grants:
        ID-token signature/issuer/audience/nonce and current Platform
        membership still need independent verification.
        """
        verifier = code_verifier.get_secret_value()
        if (
            not isinstance(code, str)
            or not 1 <= len(code) <= 4096
            or any(ch.isspace() for ch in code)
            or not _is_https_url(redirect_uri)
            or re.fullmatch(r"[A-Za-z0-9_-]{43,128}", verifier) is None
        ):
            raise ValueError("invalid code or trusted PKCE transaction")
        provider = await self.discovery()
        try:
            response = await self._client.post(
                provider.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self._client_id,
                    "code_verifier": verifier,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            if (
                len(response.content) > 65_536
                or response.headers.get("content-type", "").split(";", 1)[0].lower()
                != "application/json"
            ):
                raise OidcProviderUnavailable("OIDC token response malformed")
            token = UnverifiedOidcTokenResponse.model_validate(response.json())
            if token.token_type.lower() != "bearer":
                raise OidcProviderUnavailable("OIDC token type unsupported")
            return token
        except (httpx.HTTPError, ValidationError, ValueError, TypeError) as exc:
            raise OidcProviderUnavailable("OIDC token exchange unavailable") from exc

    async def verify_exchanged_id_token(
        self,
        *,
        tokens: UnverifiedOidcTokenResponse,
        expected_nonce: str,
    ) -> VerifiedOidcIdentity:
        """Verify real Rauthy signature before trusting a returned identity."""
        metadata = await self.discovery()
        return await verify_rauthy_id_token(
            tokens.id_token,
            expected_nonce=expected_nonce,
            issuer=metadata.issuer,
            client_id=self._client_id,
            jwks_uri=metadata.jwks_uri,
            client=self._client,
        )

    async def public_configuration(self) -> PublicOidcConfiguration:
        metadata = await self.discovery()
        return PublicOidcConfiguration(
            issuer=metadata.issuer,
            client_id=self._client_id,
            authorization_endpoint=metadata.authorization_endpoint,
            token_endpoint=metadata.token_endpoint,
            jwks_uri=metadata.jwks_uri,
            userinfo_endpoint=metadata.userinfo_endpoint,
        )
