from __future__ import annotations

import pytest

from common.account_contracts import AccountList, AccountPublic
from common.management_client import ManagementClient, ManagementClientError
from common.settings import ManagementClientSettings


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
        )
    )

    with pytest.raises(ManagementClientError, match="koba-ai-reviewer"):
        client.resolve_account("old-uuid", provider="github")


class _CachingClient(ManagementClient):
    def __init__(self) -> None:
        super().__init__(
            ManagementClientSettings(
                url="http://management:8000",
                service_token="test",
            )
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
        if path == "/internal/runtime-settings/terminal":
            return {
                "max_exec_timeout_seconds": 100,
                "max_job_runtime_seconds": 200,
            }
        raise AssertionError(path)


def test_management_client_caches_resolved_accounts_by_alias_and_id() -> None:
    client = _CachingClient()

    first = client.resolve_account("koba-ai-agent", provider="github")
    second = client.resolve_account("koba-ai-agent", provider="github")
    by_id = client.resolve_account("account-id", provider="github")

    assert first is second is by_id
    assert client.calls == ["/internal/accounts/koba-ai-agent/resolve"]


def test_management_client_caches_account_lists_and_runtime_policies() -> None:
    client = _CachingClient()

    assert client.list_accounts(provider="github").count == 0
    assert client.list_accounts(provider="github").count == 0
    assert client.mcp_runtime_policy().call_timeout_seconds == 7
    assert client.mcp_runtime_policy().call_timeout_seconds == 7
    assert client.terminal_runtime_policy().max_exec_timeout_seconds == 100
    assert client.terminal_runtime_policy().max_exec_timeout_seconds == 100

    assert client.calls == [
        "/internal/accounts",
        "/internal/runtime-settings/mcp",
        "/internal/runtime-settings/terminal",
    ]
