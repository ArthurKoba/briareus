from __future__ import annotations

import pytest
from fastmcp.server.auth.jwt_issuer import JWTIssuer, derive_jwt_key
from pydantic import AnyHttpUrl

from bridge.auth_client import LocalAuthTokenVerifier
from common.settings import GatewayAuthSettings


def _settings() -> GatewayAuthSettings:
    return GatewayAuthSettings(
        enabled=True,
        public_base_url="https://mcp.example.test",
        oauth_jwt_signing_key="0123456789abcdef0123456789abcdef",
        oauth_allowed_users=("arthurkoba",),
    )


@pytest.mark.asyncio
async def test_local_auth_verifier_accepts_matching_signed_resource() -> None:
    settings = _settings()
    resource = "https://mcp.example.test/analysis/mcp"
    signing_key = derive_jwt_key(
        low_entropy_material=settings.oauth_jwt_signing_key,
        salt="fastmcp-jwt-signing-key",
    )
    issuer = JWTIssuer(
        issuer=str(AnyHttpUrl(settings.public_base_url)),
        audience=resource,
        signing_key=signing_key,
    )
    token = issuer.issue_access_token(
        client_id="chatgpt",
        scopes=["read:user"],
        jti="test-jti",
        upstream_claims={"login": "arthurkoba", "sub": "42"},
    )

    verifier = LocalAuthTokenVerifier(settings, resource)
    access = await verifier.verify_token(token)

    assert access is not None
    assert access.resource == resource
    assert access.subject == "42"


@pytest.mark.asyncio
async def test_local_auth_verifier_rejects_wrong_audience() -> None:
    settings = _settings()
    signing_key = derive_jwt_key(
        low_entropy_material=settings.oauth_jwt_signing_key,
        salt="fastmcp-jwt-signing-key",
    )
    issuer = JWTIssuer(
        issuer=str(AnyHttpUrl(settings.public_base_url)),
        audience="https://mcp.example.test/files/mcp",
        signing_key=signing_key,
    )
    token = issuer.issue_access_token(
        client_id="chatgpt",
        scopes=["read:user"],
        jti="test-jti",
        upstream_claims={"login": "arthurkoba", "sub": "42"},
    )

    verifier = LocalAuthTokenVerifier(
        settings,
        "https://mcp.example.test/analysis/mcp",
    )

    assert await verifier.verify_token(token) is None
