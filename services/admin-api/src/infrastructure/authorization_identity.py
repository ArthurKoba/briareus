from __future__ import annotations

from urllib.parse import quote

import httpx
from pydantic import BaseModel


class LocalUserIdentity(BaseModel):
    id: str
    username: str
    enabled: bool


class AuthorizationIdentityClient:
    def __init__(self, *, base_url: str, service_token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=5.0,
            headers={"Authorization": f"Bearer {service_token}"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def by_username(self, username: str) -> LocalUserIdentity:
        response = await self._client.get(
            f"/internal/v1/users/by-username/{quote(username, safe='')}"
        )
        response.raise_for_status()
        return LocalUserIdentity.model_validate(response.json())
