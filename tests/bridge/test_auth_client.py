from __future__ import annotations

import httpx
import pytest

from bridge.auth_client import AuthServiceTokenVerifier
from common.settings import AuthClientSettings


@pytest.mark.asyncio
async def test_auth_client_verifier_sends_exact_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(
            self,
            exc_type: object,
            exc: object,
            traceback: object,
        ) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> httpx.Response:
            captured["url"] = url
            captured.update(kwargs)
            request = httpx.Request("POST", url)
            return httpx.Response(
                200,
                json={
                    "token": "token",
                    "client_id": "client",
                    "scopes": ["read:user"],
                    "resource": "https://mcp.example.test/analysis/mcp",
                    "claims": {"login": "ArthurKoba"},
                },
                request=request,
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    settings = AuthClientSettings(
        enabled=True,
        url="http://auth:8000",
        service_token="service-token",
        public_base_url="https://mcp.example.test",
    )
    verifier = AuthServiceTokenVerifier(
        settings,
        "https://mcp.example.test/analysis/mcp",
    )

    token = await verifier.verify_token("token")

    assert token is not None
    assert token.resource == "https://mcp.example.test/analysis/mcp"
    assert captured["url"] == "http://auth:8000/internal/verify"
    assert captured["json"] == {
        "token": "token",
        "resource": "https://mcp.example.test/analysis/mcp",
    }
