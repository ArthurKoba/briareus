from __future__ import annotations

from common.account_contracts import ResolvedAccount
from modules.signoz.client import SigNozClient


def _account() -> ResolvedAccount:
    return ResolvedAccount(
        id="signoz-1",
        alias="signoz-prod",
        provider="signoz",
        auth_type="signoz_api_key",
        base_url="https://signoz.example.test/base",
        enabled=True,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        credential="secret-key",
    )


def test_signoz_client_uses_pooled_transport_and_preserves_base_path() -> None:
    client = SigNozClient(_account())

    assert client._target("/api/v1/services", {"kind": "mcp"}) == (
        "/base/api/v1/services?kind=mcp"
    )
    assert client._transport.connection_count == 0
