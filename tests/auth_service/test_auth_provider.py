from __future__ import annotations

import asyncio
import hashlib
import time
from types import SimpleNamespace

import pytest

from auth_service.provider import (
    _FALLBACK_REFRESH_TOKEN_EXPIRY_SECONDS,
    _FASTMCP_ACCESS_TOKEN_EXPIRY_SECONDS,
    MultiResourceGitHubProvider,
)
from common.mcp_surfaces import allowed_resource_urls, resource_url
from common.settings import AuthServiceSettings


def _settings() -> AuthServiceSettings:
    return AuthServiceSettings(
        public_base_url="https://mcp.example.test",
        oauth_client_id="client",
        oauth_client_secret="secret",
        oauth_jwt_signing_key="0123456789abcdef0123456789abcdef",
        oauth_allowed_users=("arthurkoba",),
    )


def test_multi_resource_provider_accepts_only_declared_surfaces() -> None:
    settings = _settings()
    provider = MultiResourceGitHubProvider(settings)

    assert provider.allowed_resources == allowed_resource_urls(settings.public_base_url)
    assert provider.canonical_resource(
        "https://mcp.example.test/analysis/mcp?kb_name=analysis"
    ) == "https://mcp.example.test/analysis/mcp"

    with pytest.raises(ValueError, match="unsupported OAuth resource"):
        provider.canonical_resource("https://mcp.example.test/private/mcp")


def test_multi_resource_provider_issues_distinct_audiences_under_one_issuer() -> None:
    settings = _settings()
    provider = MultiResourceGitHubProvider(settings)

    root = resource_url(settings.public_base_url, "root")
    analysis = resource_url(settings.public_base_url, "analysis")

    root_issuer = provider.issuer_for_resource(root)
    analysis_issuer = provider.issuer_for_resource(analysis)

    assert root_issuer.issuer == analysis_issuer.issuer
    assert root_issuer.audience == root
    assert analysis_issuer.audience == analysis
    assert root_issuer.audience != analysis_issuer.audience


@pytest.mark.asyncio
async def test_upstream_claims_embed_only_allowed_identity() -> None:
    settings = _settings()
    provider = MultiResourceGitHubProvider(settings)

    class FakeValidator:
        async def verify_token(self, _token: str):
            from fastmcp.server.auth import AccessToken

            return AccessToken(
                token="upstream",
                client_id="github-user",
                scopes=["read:user"],
                subject="42",
                claims={"login": "ArthurKoba"},
            )

    provider._token_validator = FakeValidator()  # type: ignore[assignment]

    claims = await provider._extract_upstream_claims({"access_token": "upstream"})

    assert claims == {"login": "arthurkoba", "sub": "42"}


def test_fastmcp_token_lifetimes_are_client_friendly() -> None:
    assert _FASTMCP_ACCESS_TOKEN_EXPIRY_SECONDS == 24 * 60 * 60
    assert _FALLBACK_REFRESH_TOKEN_EXPIRY_SECONDS == 30 * 24 * 60 * 60


def test_refresh_token_audience_is_recovered_from_token_claims() -> None:
    settings = _settings()
    provider = MultiResourceGitHubProvider(settings)
    analysis = resource_url(settings.public_base_url, "analysis")

    import base64
    import json

    payload = base64.urlsafe_b64encode(json.dumps({"aud": analysis}).encode()).decode().rstrip("=")
    token = f"header.{payload}.signature"

    assert provider._jwt_audience_unverified(token) == analysis
    assert provider.canonical_resource(provider._jwt_audience_unverified(token)) == analysis


@pytest.mark.asyncio
async def test_concurrent_refresh_requests_are_coalesced(monkeypatch) -> None:
    from fastmcp.server.auth.providers.github import GitHubProvider
    from mcp.shared.auth import OAuthToken

    settings = _settings()
    provider = MultiResourceGitHubProvider(settings)
    analysis = resource_url(settings.public_base_url, "analysis")
    calls = 0

    async def fake_exchange(
        self,
        client,
        refresh_token,
        scopes,
    ):
        nonlocal calls
        del self, client, refresh_token, scopes
        calls += 1
        await asyncio.sleep(0.05)
        return OAuthToken(
            access_token="new-access",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="new-refresh",
            scope="read:user",
        )

    monkeypatch.setattr(GitHubProvider, "exchange_refresh_token", fake_exchange)

    client = SimpleNamespace(client_id="chatgpt-client")
    refresh = SimpleNamespace(
        token="old-refresh",
        resource=analysis,
        expires_at=int(time.time()) + 60,
        scopes=["read:user"],
    )

    first, second = await asyncio.gather(
        provider.exchange_refresh_token(client, refresh, ["read:user"]),  # type: ignore[arg-type]
        provider.exchange_refresh_token(client, refresh, ["read:user"]),  # type: ignore[arg-type]
    )

    assert calls == 1
    assert first.access_token == "new-access"
    assert second.access_token == "new-access"
    assert first.refresh_token == second.refresh_token == "new-refresh"
    grace = await provider._refresh_token_store.get(
        key=hashlib.sha256(b"old-refresh").hexdigest()
    )
    assert grace is not None
    assert grace.client_id == "chatgpt-client"
    loaded_again = await provider.load_refresh_token(client, "old-refresh")  # type: ignore[arg-type]
    assert loaded_again is not None
