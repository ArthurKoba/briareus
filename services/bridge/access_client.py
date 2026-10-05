from __future__ import annotations

from typing import Any

import httpx

from common.access_contracts import (
    AccessRequestView,
    AccountScope,
    OAuthContext,
    SessionSnapshot,
    ValidationResult,
)
from common.settings import AccessClientSettings


class AccessServiceClient:
    def __init__(self, settings: AccessClientSettings | None = None) -> None:
        self.settings = settings or AccessClientSettings()
        self._client = httpx.AsyncClient(
            base_url=self.settings.url.rstrip("/"),
            timeout=self.settings.timeout_seconds,
            headers={"Authorization": f"Bearer {self.settings.service_token}"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post(path, json=payload)
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError(f"access service returned non-object for {path}")
        return value

    async def open(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        label: str = "",
    ) -> SessionSnapshot:
        value = await self._post(
            "/v1/session/open",
            {
                **context.model_dump(),
                "surface_id": surface_id,
                "label": label,
            },
        )
        return SessionSnapshot.model_validate(value)

    async def validate(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
        tool_name: str,
        requires_full_access: bool,
        account_id: str = "",
    ) -> ValidationResult:
        value = await self._post(
            "/v1/session/validate",
            {
                **context.model_dump(),
                "surface_id": surface_id,
                "session_uid": session_uid,
                "tool_name": tool_name,
                "requires_full_access": requires_full_access,
                "account_id": account_id,
            },
        )
        return ValidationResult.model_validate(value)

    async def status(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
    ) -> SessionSnapshot:
        value = await self._post(
            "/v1/session/status",
            {
                **context.model_dump(),
                "surface_id": surface_id,
                "session_uid": session_uid,
            },
        )
        return SessionSnapshot.model_validate(value)

    async def update(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
        label: str,
    ) -> SessionSnapshot:
        value = await self._post(
            "/v1/session/update",
            {
                **context.model_dump(),
                "surface_id": surface_id,
                "session_uid": session_uid,
                "label": label,
            },
        )
        return SessionSnapshot.model_validate(value)

    async def request_full_access(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
        account_scope: AccountScope,
        account_ids: list[str],
    ) -> AccessRequestView:
        value = await self._post(
            "/v1/session/request-full-access",
            {
                **context.model_dump(),
                "surface_id": surface_id,
                "session_uid": session_uid,
                "account_scope": account_scope,
                "account_ids": account_ids,
            },
        )
        return AccessRequestView.model_validate(value)

    async def request_extension(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
        requested_expires_at: int,
    ) -> AccessRequestView:
        value = await self._post(
            "/v1/session/request-extension",
            {
                **context.model_dump(),
                "surface_id": surface_id,
                "session_uid": session_uid,
                "requested_expires_at": requested_expires_at,
            },
        )
        return AccessRequestView.model_validate(value)

    async def close_session(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
    ) -> SessionSnapshot:
        value = await self._post(
            "/v1/session/close",
            {
                **context.model_dump(),
                "surface_id": surface_id,
                "session_uid": session_uid,
            },
        )
        return SessionSnapshot.model_validate(value)

    async def reissue(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
        label: str = "",
    ) -> SessionSnapshot:
        value = await self._post(
            "/v1/session/reissue",
            {
                **context.model_dump(),
                "surface_id": surface_id,
                "session_uid": session_uid,
                "label": label,
            },
        )
        return SessionSnapshot.model_validate(value)
