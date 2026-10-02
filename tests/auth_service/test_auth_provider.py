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
async def test_concurrent_refresh_requests_are_coalesced_and_replayed(monkeypatch) -> None:
    from fastmcp.server.auth.providers.github import GitHubProvider
    from mcp.server.auth.provider import RefreshToken
    from mcp.shared.auth import OAuthToken

    settings = _settings()
    provider = MultiResourceGitHubProvider(settings)
    analysis = resource_url(settings.public_base_url, "analysis")
    calls = 0
    old_jti = f"old-jti-{time.time_ns()}"
    old_token = provider.issuer_for_resource(analysis).issue_refresh_token(
        client_id="chatgpt-client",
        scopes=["read:user"],
        jti=old_jti,
        expires_in=60,
    )

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
    refresh = RefreshToken(
        token=old_token,
        client_id="chatgpt-client",
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

    provider._refresh_exchange_replays.clear()
    loaded_again = await provider.load_refresh_token(client, old_token)  # type: ignore[arg-type]
    assert loaded_again is not None
    third = await provider.exchange_refresh_token(
        client, loaded_again, ["read:user"]  # type: ignore[arg-type]
    )
    assert calls == 1
    assert third.access_token == "new-access"
    assert third.refresh_token == "new-refresh"


@pytest.mark.asyncio
async def test_refresh_retries_once_when_upstream_rotation_wins_race(monkeypatch) -> None:
    from fastmcp.server.auth.oauth_proxy.models import JTIMapping, UpstreamTokenSet
    from fastmcp.server.auth.providers.github import GitHubProvider
    from mcp.server.auth.provider import RefreshToken, TokenError
    from mcp.shared.auth import OAuthToken

    settings = _settings()
    provider = MultiResourceGitHubProvider(settings)
    analysis = resource_url(settings.public_base_url, "analysis")
    client = SimpleNamespace(client_id="chatgpt-client")
    old_jti = f"race-jti-{time.time_ns()}"
    upstream_id = f"upstream-{time.time_ns()}"
    old_upstream_refresh = f"upstream-old-{time.time_ns()}"
    new_upstream_refresh = f"upstream-new-{time.time_ns()}"
    old_token = provider.issuer_for_resource(analysis).issue_refresh_token(
        client_id="chatgpt-client",
        scopes=["read:user"],
        jti=old_jti,
        expires_in=60,
    )
    refresh = RefreshToken(
        token=old_token,
        client_id="chatgpt-client",
        resource=analysis,
        expires_at=int(time.time()) + 60,
        scopes=["read:user"],
    )
    await provider._jti_mapping_store.put(
        key=old_jti,
        value=JTIMapping(
            jti=old_jti,
            upstream_token_id=upstream_id,
            created_at=time.time(),
        ),
        ttl=60,
    )
    await provider._upstream_token_store.put(
        key=upstream_id,
        value=UpstreamTokenSet(
            upstream_token_id=upstream_id,
            access_token="upstream-access",
            refresh_token=old_upstream_refresh,
            refresh_token_expires_at=time.time() + 3600,
            expires_at=time.time() + 3600,
            token_type="bearer",
            scope="read:user",
            client_id="github-client",
            created_at=time.time(),
        ),
        ttl=3600,
    )
    calls = 0

    async def fake_exchange(
        self,
        client_arg,
        refresh_arg,
        scopes_arg,
    ):
        nonlocal calls
        del self, client_arg, refresh_arg, scopes_arg
        calls += 1
        if calls == 1:
            current = await provider._upstream_token_store.get(key=upstream_id)
            assert current is not None
            current.refresh_token = new_upstream_refresh
            await provider._upstream_token_store.put(
                key=upstream_id,
                value=current,
                ttl=3600,
            )
            raise TokenError(
                "invalid_grant",
                "Upstream refresh failed: bad_refresh_token",
            )
        return OAuthToken(
            access_token="recovered-access",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="recovered-refresh",
            scope="read:user",
        )

    monkeypatch.setattr(GitHubProvider, "exchange_refresh_token", fake_exchange)

    result = await provider.exchange_refresh_token(
        client, refresh, ["read:user"]  # type: ignore[arg-type]
    )

    assert calls == 2
    assert result.access_token == "recovered-access"
    assert result.refresh_token == "recovered-refresh"

