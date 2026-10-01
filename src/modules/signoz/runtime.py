from __future__ import annotations

import threading

from common.management_client import ManagementClient
from common.models import JsonObject, JsonValue
from common.runtime_annotations import READ_EXTERNAL
from common.runtime_common import build_private_mcp, management_client, private_http_app
from common.settings import ManagementClientSettings, PrivateRuntimeSettings

from .client import SigNozClient


class SigNozRuntimeContext:
    def __init__(self, management: ManagementClient) -> None:
        self.management = management
        self._lock = threading.Lock()
        self._clients: dict[str, tuple[str, SigNozClient]] = {}

    def accounts(self) -> JsonObject:
        return self.management.list_accounts(provider="signoz").to_json()

    def client(self, account_id: str) -> SigNozClient:
        account = self.management.resolve_account(account_id, provider="signoz")
        with self._lock:
            cached = self._clients.get(account.id)
            if cached is not None and cached[0] == account.updated_at:
                return cached[1]
            client = SigNozClient(account)
            self._clients[account.id] = (account.updated_at, client)
            return client


_private = PrivateRuntimeSettings()
_management = management_client(ManagementClientSettings())
_context = SigNozRuntimeContext(_management)
mcp = build_private_mcp("signoz", _management, observability_scope="signoz")


@mcp.tool(title="SigNoz accounts", annotations=READ_EXTERNAL)
def signoz_accounts() -> JsonObject:
    return _context.accounts()


@mcp.tool(title="SigNoz connection", annotations=READ_EXTERNAL)
def signoz_connection(account_id: str) -> JsonObject:
    return _context.client(account_id).account_summary()


@mcp.tool(title="SigNoz identity", annotations=READ_EXTERNAL)
def signoz_whoami(account_id: str) -> JsonObject:
    return _context.client(account_id).whoami()


@mcp.tool(title="SigNoz search logs", annotations=READ_EXTERNAL)
def signoz_search_logs(
    account_id: str,
    start_ms: int,
    end_ms: int,
    filter_expression: str = "",
    limit: int = 100,
    offset: int = 0,
) -> JsonValue:
    return _context.client(account_id).search_logs(
        start_ms=start_ms,
        end_ms=end_ms,
        filter_expression=filter_expression,
        limit=limit,
        offset=offset,
    )


@mcp.tool(title="SigNoz search traces", annotations=READ_EXTERNAL)
def signoz_search_traces(
    account_id: str,
    start_ms: int,
    end_ms: int,
    filter_expression: str = "",
    limit: int = 100,
    offset: int = 0,
) -> JsonValue:
    return _context.client(account_id).search_traces(
        start_ms=start_ms,
        end_ms=end_ms,
        filter_expression=filter_expression,
        limit=limit,
        offset=offset,
    )


@mcp.tool(title="SigNoz query range", annotations=READ_EXTERNAL)
def signoz_query_range(account_id: str, query: JsonObject) -> JsonValue:
    return _context.client(account_id).query_range(query)


@mcp.tool(title="SigNoz services", annotations=READ_EXTERNAL)
def signoz_list_services(account_id: str, start: str, end: str) -> JsonValue:
    return _context.client(account_id).list_services(start=start, end=end)


@mcp.tool(title="SigNoz field keys", annotations=READ_EXTERNAL)
def signoz_field_keys(
    account_id: str,
    signal: str,
    search_text: str = "",
    metric_name: str = "",
) -> JsonValue:
    return _context.client(account_id).field_keys(
        signal=signal,
        search_text=search_text,
        metric_name=metric_name,
    )


@mcp.tool(title="SigNoz field values", annotations=READ_EXTERNAL)
def signoz_field_values(
    account_id: str,
    signal: str,
    name: str,
    search_text: str = "",
    metric_name: str = "",
) -> JsonValue:
    return _context.client(account_id).field_values(
        signal=signal,
        name=name,
        search_text=search_text,
        metric_name=metric_name,
    )


app = private_http_app(mcp, _private)
