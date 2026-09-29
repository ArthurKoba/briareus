from __future__ import annotations

import pytest

from auth_service.provider import MultiResourceGitHubProvider
from common.mcp_surfaces import allowed_resource_urls, resource_url
from common.settings import AuthServiceSettings


def _settings() -> AuthServiceSettings:
    return AuthServiceSettings(
        public_base_url="https://mcp.example.test",
        oauth_client_id="client",
        oauth_client_secret="secret",
        oauth_jwt_signing_key="0123456789abcdef0123456789abcdef",
        oauth_allowed_users=("arthurkoba",),
        service_token="service-token",
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
