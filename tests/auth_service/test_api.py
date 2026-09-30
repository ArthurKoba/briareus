from __future__ import annotations

from fastmcp.server.auth import AccessToken
from starlette.testclient import TestClient

from auth_service.api import build_auth_app
from common.settings import AuthServiceSettings


class FakeProvider:
    def get_routes(self, mcp_path: str | None = None):
        assert mcp_path == "/mcp"
        return []

    def canonical_resource(self, value: str | None) -> str:
        if value != "https://mcp.example.test/analysis/mcp":
            raise ValueError("unsupported")
        return value

    async def load_access_token(self, token: str) -> AccessToken | None:
        if token == "good":
            return AccessToken(
                token=token,
                client_id="client",
                scopes=["read:user"],
                resource="https://mcp.example.test/analysis/mcp",
                claims={"login": "ArthurKoba"},
            )
        if token == "wrong-user":
            return AccessToken(
                token=token,
                client_id="client",
                scopes=["read:user"],
                resource="https://mcp.example.test/analysis/mcp",
                claims={"login": "SomeoneElse"},
            )
        return None


def _settings() -> AuthServiceSettings:
    return AuthServiceSettings(
        public_base_url="https://mcp.example.test",
        oauth_client_id="client",
        oauth_client_secret="secret",
        oauth_jwt_signing_key="0123456789abcdef0123456789abcdef",
        oauth_allowed_users=("arthurkoba",),
        service_token="service-token",
    )


def test_internal_verify_requires_service_auth_and_allowed_user() -> None:
    app = build_auth_app(FakeProvider(), _settings())  # type: ignore[arg-type]

    with TestClient(app) as client:
        unauthorized = client.post(
            "/internal/verify",
            json={
                "token": "good",
                "resource": "https://mcp.example.test/analysis/mcp",
            },
        )
        assert unauthorized.status_code == 401

        wrong_user = client.post(
            "/internal/verify",
            headers={"Authorization": "Bearer service-token"},
            json={
                "token": "wrong-user",
                "resource": "https://mcp.example.test/analysis/mcp",
            },
        )
        assert wrong_user.status_code == 403

        valid = client.post(
            "/internal/verify",
            headers={"Authorization": "Bearer service-token"},
            json={
                "token": "good",
                "resource": "https://mcp.example.test/analysis/mcp",
            },
        )

    assert valid.status_code == 200
    assert valid.json()["resource"] == "https://mcp.example.test/analysis/mcp"


def test_internal_verify_rejects_wrong_resource() -> None:
    app = build_auth_app(FakeProvider(), _settings())  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.post(
            "/internal/verify",
            headers={"Authorization": "Bearer service-token"},
            json={
                "token": "good",
                "resource": "https://mcp.example.test/files/mcp",
            },
        )

    assert response.status_code == 400
