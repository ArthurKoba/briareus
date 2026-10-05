from __future__ import annotations

import unittest

from auth_service.access.service import AccessService
from common.access_contracts import SessionOpenRequest, SessionSnapshot, SessionValidateRequest
from common.settings import AuthServiceSettings, ValkeySettings


class FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def key(self, *parts: str) -> str:
        return ":".join(parts)

    def get_json(self, key: str) -> object | None:
        return self.values.get(key)

    def set_json(self, key: str, value: object, *, ttl_seconds: int) -> bool:
        del ttl_seconds
        self.values[key] = value
        return True

    def delete(self, *keys: str) -> bool:
        for key in keys:
            self.values.pop(key, None)
        return True


class FakeRepository:
    def __init__(
        self,
        session: SessionSnapshot,
        *,
        mode: str = "session_enforced",
        blocked: bool = False,
    ) -> None:
        self.session = session
        self.mode = mode
        self.blocked = blocked

    async def get_session(self, uid: str) -> SessionSnapshot | None:
        return self.session if uid == self.session.uid else None

    async def get_mode(self, user_id: str, surface_id: int) -> str:
        del user_id, surface_id
        return self.mode

    async def oauth_context_blocked(self, oauth_session_id: str, *, user_id: str) -> bool:
        del oauth_session_id, user_id
        return self.blocked


def settings() -> AuthServiceSettings:
    return AuthServiceSettings.model_construct(
        postgres_host="postgres",
        postgres_port=5432,
        postgres_db="auth",
        postgres_user="user",
        postgres_password="pass",
        gateway_service_token="gateway",
        admin_service_token="admin",
                default_session_ttl_seconds=3600,
        session_cache_ttl_seconds=300,
        invalid_attempt_soft_limit=5,
        invalid_attempt_oauth_revoke_limit=50,
        invalid_attempt_window_seconds=600,
        invalid_attempt_backoff_seconds=30,
    )


def snapshot(
    *,
    access_level: str = "read_only",
    account_scope: str = "none",
    account_ids: list[str] | None = None,
    surface_id: int = 4,
) -> SessionSnapshot:
    return SessionSnapshot.model_validate(
        {
            "id": "session-record-1",
            "uid": "session-uid-1234567890",
            "user_id": "user-1",
            "oauth_client_id": "client-1",
            "oauth_session_id": "oauth-1",
            "surface_id": surface_id,
            "access_level": access_level,
            "account_scope": account_scope,
            "account_ids": account_ids or [],
            "status": "active",
            "label": "",
            "expires_at": 0,
        }
    )


def request(
    *,
    requires_full_access: bool,
    account_id: str = "",
    session_uid: str = "session-uid-1234567890",
    surface_id: int = 4,
) -> SessionValidateRequest:
    return SessionValidateRequest(
        user_id="user-1",
        client_id="client-1",
        oauth_session_id="oauth-1",
        surface_id=surface_id,
        session_uid=session_uid,
        tool_name="tool",
        requires_full_access=requires_full_access,
        account_id=account_id,
    )


class AccessDecisionTest(unittest.IsolatedAsyncioTestCase):
    async def build(
        self,
        session: SessionSnapshot,
        *,
        mode: str = "session_enforced",
        blocked: bool = False,
    ) -> AccessService:
        repository = FakeRepository(session, mode=mode, blocked=blocked)
        return AccessService(
            settings=settings(),
            repository=repository,  # type: ignore[arg-type]
            cache=FakeCache(),  # type: ignore[arg-type]
            cache_settings=ValkeySettings(url="redis://127.0.0.1:1/0"),
        )

    async def test_read_only_session_allows_read_only_and_denies_mutation(self) -> None:
        service = await self.build(snapshot())
        try:
            read = await service.validate(request(requires_full_access=False))
            write = await service.validate(request(requires_full_access=True))
        finally:
            await service.close()

        self.assertTrue(read.allowed)
        self.assertEqual(read.code, "allowed")
        self.assertFalse(write.allowed)
        self.assertEqual(write.code, "full_access_required")

    async def test_selected_account_scope_applies_to_mutations(self) -> None:
        service = await self.build(
            snapshot(
                access_level="full_access",
                account_scope="selected",
                account_ids=["account-1"],
                surface_id=1,
            )
        )
        try:
            allowed = await service.validate(
                request(
                    requires_full_access=True,
                    account_id="account-1",
                    surface_id=1,
                )
            )
            wrong_account = await service.validate(
                request(
                    requires_full_access=True,
                    account_id="account-2",
                    surface_id=1,
                )
            )
            missing_account = await service.validate(
                request(requires_full_access=True, surface_id=1)
            )
        finally:
            await service.close()

        self.assertTrue(allowed.allowed)
        self.assertFalse(wrong_account.allowed)
        self.assertEqual(wrong_account.code, "account_scope_denied")
        self.assertFalse(missing_account.allowed)
        self.assertEqual(missing_account.code, "account_scope_denied")

    async def test_account_backed_none_denies_provider_default_account(self) -> None:
        service = await self.build(
            snapshot(
                access_level="full_access",
                account_scope="none",
                surface_id=1,
            )
        )
        try:
            result = await service.validate(
                request(requires_full_access=True, surface_id=1)
            )
        finally:
            await service.close()

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "account_scope_denied")

    async def test_account_backed_all_allows_provider_default_account(self) -> None:
        service = await self.build(
            snapshot(
                access_level="full_access",
                account_scope="all",
                surface_id=1,
            )
        )
        try:
            result = await service.validate(
                request(requires_full_access=True, surface_id=1)
            )
        finally:
            await service.close()

        self.assertTrue(result.allowed)
        self.assertEqual(result.code, "allowed")

    async def test_blocked_oauth_context_cannot_open_new_session(self) -> None:
        service = await self.build(snapshot(), blocked=True)
        try:
            with self.assertRaisesRegex(PermissionError, "oauth_session_revoked"):
                await service.open_session(
                    SessionOpenRequest(
                        user_id="user-1",
                        client_id="client-1",
                        oauth_session_id="oauth-1",
                        surface_id=4,
                        label="blocked",
                    )
                )
        finally:
            await service.close()

    async def test_unrestricted_surface_skips_agent_session_requirement(self) -> None:
        service = await self.build(snapshot(), mode="unrestricted")
        try:
            result = await service.validate(
                request(requires_full_access=True, session_uid="")
            )
        finally:
            await service.close()

        self.assertTrue(result.allowed)
        self.assertEqual(result.code, "unrestricted")


if __name__ == "__main__":
    unittest.main()
