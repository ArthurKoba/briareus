"""Rauthy OpenID Connect discovery through standards, not private APIs.

This is an upstream Identity adapter, NOT an alternate issuer, password store,
or a grant authority. Public configuration may be forwarded to the browser;
privileged Rauthy Admin REST remains a separate, unexposed integration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


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
