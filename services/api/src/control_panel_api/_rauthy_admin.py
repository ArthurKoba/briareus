"""Private Rauthy REST authentication; never reuse an admin browser session."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

_INTERNAL_ORIGIN = "http://briareus-rauthy:8080"
_USERS_READ = "/auth/v1/users"


class RauthyAdminError(Exception):
    """Provider administration is unavailable or rejected."""


class RauthyAdminKeyRejected(RauthyAdminError):
    """Configured key is invalid or lacks the required scope."""


class RauthyAdminUnavailable(RauthyAdminError):
    """Private identity management endpoint cannot be verified."""


class RauthyAdminClient:
    """Never exposes credentials, response bodies or network routing to users."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        # Provider owns credential syntax and authentication. Do not reject
        # a nonstandard but syntactically safe key at application startup.
        # Local validation guards only HTTP header injection/bounds; a bad
        # service credential is rejected by the actual upstream (401/403).
        raw = api_key.get_secret_value()
        if (
            not 1 <= len(raw) <= 4096
            or not raw.isascii()
            or any(ch.isspace() or ord(ch) < 33 or ord(ch) == 127 for ch in raw)
        ):
            raise RauthyAdminKeyRejected("unsafe configured Rauthy API Key")
        self._credential = api_key
        self._client = http_client or httpx.AsyncClient(
            base_url=_INTERNAL_ORIGIN,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(5, connect=2),
        )
        self._owns_client = http_client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def probe_user_read(self) -> None:
        """GET /auth/v1/users requires Rauthy Users:read in v0.37.1."""
        try:
            async with self._client.stream(
                "GET",
                _USERS_READ,
                headers={
                    "Authorization": f"API-Key {self._credential.get_secret_value()}",
                    "Accept": "application/json",
                },
                follow_redirects=False,
            ) as response:
                if response.status_code in {401, 403}:
                    raise RauthyAdminKeyRejected("service key rejected or insufficient scope")
                if response.status_code != 200:
                    raise RauthyAdminUnavailable(
                        f"private Users:read failed: HTTP {response.status_code}"
                    )
                if (
                    response.headers.get("content-type", "").split(";", 1)[0].lower()
                    != "application/json"
                ):
                    raise RauthyAdminUnavailable("private Users:read not JSON")
        except httpx.HTTPError as exc:
            raise RauthyAdminUnavailable("private Rauthy API unavailable") from exc
