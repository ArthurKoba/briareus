from __future__ import annotations

import pytest

from common.account_contracts import AccountList, AccountPublic, InvocationEvent
from common.management_client import ManagementClient, ManagementClientError
from common.models import JsonValue
from common.settings import ManagementClientSettings


class _MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, JsonValue] = {}

    def key(self, *parts: str) -> str:
        return ":".join(part.strip().casefold() for part in parts if part.strip())

    def get_json(self, key: str) -> JsonValue | None:
        return self.values.get(key)

    def set_json(self, key: str, value: object, *, ttl_seconds: int) -> bool:
        del ttl_seconds
        assert isinstance(value, (dict, list, str, int, float, bool)) or value is None
        self.values[key] = value
        return True

    def delete(self, *keys: str) -> bool:
        for key in keys:
            self.values.pop(key, None)
        return True


class _Client(ManagementClient):
    def _request(self, method, path, *, query=None, payload=None, expect_body=True):
        del method, query, payload, expect_body
        if path.endswith("/resolve"):
            raise ManagementClientError('management HTTP 404: {"detail":"not found"}')
        if path == "/internal/accounts":
            return AccountList(
                accounts=[
                    AccountPublic(
                        id="new-id",
                        alias="koba-ai-reviewer",
                        provider="github",
                        auth_type="github_app",
                        base_url="https://api.github.com",
                        external_id="4978904",
                        verify_tls=True,
                        ca_cert_pem=None,
                        enabled=True,
                        created_at="2026-10-01T00:00:00+00:00",
                        updated_at="2026-10-01T00:00:00+00:00",
                    )
                ],
                count=1,
            ).to_json()
        raise AssertionError(path)


def test_stale_account_id_error_points_to_stable_alias() -> None:
    client = _Client(
        ManagementClientSettings(
            url="http://management:8000",
            service_token="test",
        ),
        cache=_MemoryCache(),
    )

    with pytest.raises(ManagementClientError, match="koba-ai-reviewer"):
        client.resolve_account("old-uuid", provider="github")


class _CachingClient(ManagementClient):
    def __init__(self) -> None:
        super().__init__(
            ManagementClientSettings(
                url="http://management:8000",
                service_token="test",
            ),
            cache=_MemoryCache(),
        )
        self.calls: list[str] = []

    def _request(self, method, path, *, query=None, payload=None, expect_body=True):
        del method, query, payload, expect_body
        self.calls.append(path)
        if path.endswith("/resolve"):
            return {
                "id": "account-id",
                "alias": "koba-ai-agent",
                "provider": "github",
                "auth_type": "github_app",
                "base_url": "https://api.github.com",
                "external_id": "4970571",
                "verify_tls": True,
                "ca_cert_pem": None,
                "enabled": True,
                "created_at": "2026-10-01T00:00:00+00:00",
                "updated_at": "2026-10-01T00:00:00+00:00",
                "credential": "secret",
            }
        if path == "/internal/accounts":
            return {"accounts": [], "count": 0}
        if path == "/internal/runtime-settings/mcp":
            return {"call_timeout_seconds": 7}
        if path == "/internal/runtime-settings/github":
            return {
                "local_first_guidance": True,
                "local_git_transport_enabled": False,
                "remote_source_mutations_enabled": True,
            }
        if path == "/internal/runtime-settings/terminal":
            return {
                "max_exec_timeout_seconds": 100,
                "max_job_runtime_seconds": 200,
            }
        if path == "/internal/events/batch":
            return {}
        raise AssertionError(path)


def test_management_client_caches_resolved_accounts_by_alias_and_id() -> None:
    client = _CachingClient()

    first = client.resolve_account("koba-ai-agent", provider="github")
    second = client.resolve_account("koba-ai-agent", provider="github")
    by_id = client.resolve_account("account-id", provider="github")

    assert first == second == by_id
    assert client.calls == ["/internal/accounts/koba-ai-agent/resolve"]


def test_management_client_caches_account_lists_and_runtime_policies() -> None:
    client = _CachingClient()

    assert client.list_accounts(provider="github").count == 0
    assert client.list_accounts(provider="github").count == 0
    assert client.mcp_runtime_policy().call_timeout_seconds == 7
    assert client.mcp_runtime_policy().call_timeout_seconds == 7
    assert client.terminal_runtime_policy().max_exec_timeout_seconds == 100
    assert client.terminal_runtime_policy().max_exec_timeout_seconds == 100
    assert client.github_runtime_policy().local_git_transport_enabled is False
    assert client.github_runtime_policy().local_git_transport_enabled is False

    assert client.calls == [
        "/internal/accounts",
        "/internal/runtime-settings/mcp",
        "/internal/runtime-settings/terminal",
        "/internal/runtime-settings/github",
    ]


def test_management_client_batches_invocation_events_into_one_request() -> None:
    client = _CachingClient()
    events = [
        InvocationEvent(
            module="github",
            tool=f"tool_{index}",
            status="success",
            duration_ms=1.0,
        )
        for index in range(3)
    ]

    client.record_invocations(events)

    assert client.calls == ["/internal/events/batch"]


def test_management_client_uses_pooled_transport_and_preserves_base_path() -> None:
    client = ManagementClient(
        ManagementClientSettings(
            url="http://management:8000/control",
            service_token="test",
        ),
        cache=_MemoryCache(),
    )

    assert client._target("/internal/accounts", {"provider": "github"}) == (
        "/control/internal/accounts?provider=github"
    )
    assert client._transport.connection_count == 0
