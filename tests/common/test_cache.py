from __future__ import annotations

import valkey

from common.cache import CacheKeys, SharedCache
from common.settings import ValkeySettings


class _Client:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str):
        return self.values.get(key)

    def set(self, key: str, value: str, *, ex: int):
        assert ex > 0
        self.values[key] = value
        return True

    def delete(self, *keys: str):
        for key in keys:
            self.values.pop(key, None)
        return len(keys)

    def ping(self):
        return True


class _BrokenClient:
    def get(self, key: str):
        del key
        raise valkey.exceptions.ConnectionError("offline")

    def set(self, key: str, value: str, *, ex: int):
        del key, value, ex
        raise valkey.exceptions.ConnectionError("offline")

    def delete(self, *keys: str):
        del keys
        raise valkey.exceptions.ConnectionError("offline")

    def ping(self):
        raise valkey.exceptions.ConnectionError("offline")


def _cache(client) -> SharedCache:
    cache = SharedCache(ValkeySettings(namespace="Test:Cache"))
    cache._client = client
    return cache


def test_shared_cache_serializes_json_and_normalizes_keys() -> None:
    cache = _cache(_Client())
    key = cache.key("Accounts", "Resolved", "GitHub", "KOBA-AI-AGENT")

    assert key == "Test:Cache:accounts:resolved:github:koba-ai-agent"
    assert cache.set_json(key, {"enabled": True}, ttl_seconds=30) is True
    assert cache.get_json(key) == {"enabled": True}
    assert cache.delete(key) is True
    assert cache.get_json(key) is None


def test_shared_cache_fails_open_when_valkey_is_unavailable() -> None:
    cache = _cache(_BrokenClient())
    key = cache.key("system", "runtime", "mcp")

    assert cache.get_json(key) is None
    assert cache.set_json(key, {"call_timeout_seconds": 5}, ttl_seconds=30) is False
    assert cache.delete(key) is False
    assert cache.ping() is False


def test_cache_keys_cover_account_alias_id_lists_and_system_policies() -> None:
    cache = _cache(_Client())
    keys = CacheKeys(cache)

    invalidation = keys.account_invalidation_keys(
        "github",
        account_id="account-id",
        alias="koba-ai-agent",
    )

    assert keys.account("github", "koba-ai-agent") in invalidation
    assert keys.account("github", "account-id") in invalidation
    assert keys.account_list("github") in invalidation
    assert keys.account_list() in invalidation
    assert keys.mcp_policy().endswith(":system:runtime:mcp")
    assert keys.terminal_policy().endswith(":system:runtime:terminal")
