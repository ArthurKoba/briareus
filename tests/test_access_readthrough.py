from __future__ import annotations

import unittest

from authorization.access.control import AccessControl
from common.access_contracts import SessionSnapshot
from common.settings import AuthorizationServiceSettings, ValkeySettings


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
    def __init__(self, session: SessionSnapshot) -> None:
        self.session = session
        self.reads = 0

    async def get_session(self, uid: str) -> SessionSnapshot | None:
        self.reads += 1
        return self.session if uid == self.session.uid else None


class AccessReadThroughTest(unittest.IsolatedAsyncioTestCase):
    async def test_cache_miss_reads_durable_session_then_reuses_cache(self) -> None:
        session = SessionSnapshot(
            id="session-record-1",
            uid="session-uid-1234567890",
            user_id="user-1",
            oauth_client_id="client-1",
            oauth_session_id="oauth-1",
            surface_id=1,
            access_level="read_only",
            account_scope="none",
            account_ids=[],
            status="active",
            label="",
            expires_at=0,
        )
        repository = FakeRepository(session)
        cache = FakeCache()
        settings = AuthorizationServiceSettings.model_construct(
            postgres_host="postgres",
            postgres_port=5432,
            postgres_db="authorization",
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
        service = AccessControl(
            settings=settings,
            repository=repository,  # type: ignore[arg-type]
            cache=cache,  # type: ignore[arg-type]
            cache_settings=ValkeySettings(url="redis://127.0.0.1:1/0"),
        )
        try:
            first = await service._load_session(session.uid)
            second = await service._load_session(session.uid)
        finally:
            await service.close()

        self.assertEqual(first, session)
        self.assertEqual(second, session)
        self.assertEqual(repository.reads, 1)


if __name__ == "__main__":
    unittest.main()
