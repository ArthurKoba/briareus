from __future__ import annotations

from typing import Any

import httpx

from common.access_contracts import AccessLevel, AccountScope, EnforcementMode
from common.models import JsonObject, json_object


class AuthorizationAccessAdminClient:
    def __init__(self, *, base_url: str, service_token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=5.0,
            headers={"Authorization": f"Bearer {service_token}"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._client.request(method, path, json=json)
        response.raise_for_status()
        if response.status_code == 204:
            return {}
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("authorization access API returned non-object response")
        return value

    @staticmethod
    def _object_list(value: object) -> list[JsonObject]:
        if not isinstance(value, list):
            return []
        return [json_object(item) for item in value if isinstance(item, dict)]

    async def sessions(self, user_id: str) -> list[JsonObject]:
        payload = await self._request("GET", f"/v1/admin/users/{user_id}/sessions")
        return self._object_list(payload.get("sessions", []))

    async def requests(self, user_id: str) -> list[JsonObject]:
        payload = await self._request("GET", f"/v1/admin/users/{user_id}/requests")
        return self._object_list(payload.get("requests", []))

    async def controls(self, user_id: str) -> list[JsonObject]:
        payload = await self._request("GET", f"/v1/admin/users/{user_id}/controls")
        return self._object_list(payload.get("controls", []))

    async def resolve_request(
        self,
        request_id: str,
        *,
        admin_user_id: str,
        approve: bool,
        account_scope: AccountScope | None,
        account_ids: list[str] | None,
        expires_at: int | None,
    ) -> JsonObject:
        payload = await self._request(
            "POST",
            f"/v1/admin/requests/{request_id}/resolve",
            json={
                "admin_user_id": admin_user_id,
                "approve": approve,
                "account_scope": account_scope,
                "account_ids": account_ids,
                "expires_at": expires_at,
            },
        )
        return json_object(payload)

    async def update_session(
        self,
        session_id: str,
        *,
        admin_user_id: str,
        access_level: AccessLevel | None = None,
        account_scope: AccountScope | None = None,
        account_ids: list[str] | None = None,
        expires_at: int | None = None,
        label: str | None = None,
    ) -> JsonObject:
        payload = await self._request(
            "PATCH",
            f"/v1/admin/sessions/{session_id}",
            json={
                "admin_user_id": admin_user_id,
                "access_level": access_level,
                "account_scope": account_scope,
                "account_ids": account_ids,
                "expires_at": expires_at,
                "label": label,
            },
        )
        return json_object(payload)

    async def revoke_session(self, session_id: str, *, admin_user_id: str) -> None:
        await self._request(
            "POST",
            f"/v1/admin/sessions/{session_id}/revoke",
            json={"admin_user_id": admin_user_id},
        )

    async def set_controls(
        self,
        *,
        user_id: str,
        items: list[tuple[int, EnforcementMode]],
    ) -> list[JsonObject]:
        payload = await self._request(
            "PUT",
            "/v1/admin/controls/batch",
            json={
                "items": [
                    {
                        "user_id": user_id,
                        "surface_id": surface_id,
                        "mode": mode,
                    }
                    for surface_id, mode in items
                ]
            },
        )
        return self._object_list(payload.get("controls", []))
