from __future__ import annotations

import httpx
from fastmcp.server.auth import AccessToken, TokenVerifier
from common.settings import AuthClientSettings


class AuthServiceTokenVerifier(TokenVerifier):
    """Validate one exact MCP resource through the private auth runtime."""

    def __init__(self, settings: AuthClientSettings, resource: str) -> None:
        super().__init__(required_scopes=["read:user"])
        self.settings = settings
        self.resource = resource

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.timeout_seconds,
            ) as client:
                response = await client.post(
                    f"{self.settings.url.rstrip('/')}/internal/verify",
                    headers={
                        "Authorization": f"Bearer {self.settings.service_token}",
                    },
                    json={
                        "token": token,
                        "resource": self.resource,
                    },
                )
        except httpx.RequestError:
            return None

        if response.status_code != 200:
            return None

        try:
            return AccessToken.model_validate(response.json())
        except (ValueError, TypeError):
            return None
