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
