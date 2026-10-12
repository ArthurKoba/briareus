from __future__ import annotations

import threading
from typing import Literal

from common.admin_api_client import AdminApiClient
from common.models import JsonObject, JsonValue
from common.runtime_annotations import READ_EXTERNAL
from common.runtime_common import admin_api_client, private_http_app
from common.settings import AdminApiClientSettings, PrivateRuntimeSettings
from modules.coolify.client import CoolifyClient
from modules.project_runtime.runtime_telemetry import build_runtime_mcp
from modules.signoz.client import SigNozClient

ProviderName = Literal["signoz", "coolify"]


class ObservabilityRuntimeContext:
    def __init__(self, admin_api: AdminApiClient) -> None:
        self.admin_api = admin_api
        self._lock = threading.Lock()
        self._signoz: dict[str, tuple[str, SigNozClient]] = {}
        self._coolify: dict[str, tuple[str, CoolifyClient]] = {}

    def sources(self, provider: ProviderName | None = None) -> JsonObject:
        if provider is not None:
            result = self.admin_api.list_accounts(provider=provider).to_json()
            return {"sources": result["accounts"], "count": result["count"]}
        signoz = self.admin_api.list_accounts(provider="signoz")
        coolify = self.admin_api.list_accounts(provider="coolify")
        sources = [*signoz.accounts, *coolify.accounts]
        return {
            "sources": [item.model_dump(mode="json") for item in sources],
            "count": len(sources),
        }

    def signoz(self, account_id: str) -> SigNozClient:
        account = self.admin_api.resolve_account(account_id, provider="signoz")
        with self._lock:
            cached = self._signoz.get(account.id)
            if cached is not None and cached[0] == account.updated_at:
                return cached[1]
            client = SigNozClient(account)
            self._signoz[account.id] = (account.updated_at, client)
            return client

    def coolify(self, account_id: str) -> CoolifyClient:
        account = self.admin_api.resolve_account(account_id, provider="coolify")
        with self._lock:
            cached = self._coolify.get(account.id)
            if cached is not None and cached[0] == account.updated_at:
                return cached[1]
            client = CoolifyClient(account)
            self._coolify[account.id] = (account.updated_at, client)
            return client


_private = PrivateRuntimeSettings()
_admin_api = admin_api_client(AdminApiClientSettings())
_context = ObservabilityRuntimeContext(_admin_api)
mcp, _runtime_telemetry = build_runtime_mcp("infrastructure", name="observability")


@mcp.tool(title="Observability sources", annotations=READ_EXTERNAL)
def observability_sources(provider: ProviderName | None = None) -> JsonObject:
    """List configured SigNoz and Coolify sources. Use alias/id as account_id in other tools."""
    return _context.sources(provider)


@mcp.tool(title="Observability source connection", annotations=READ_EXTERNAL)
def observability_connection(provider: ProviderName, account_id: str) -> JsonObject:
    """Show safe metadata for one configured source without exposing its credential."""
    if provider == "signoz":
        return _context.signoz(account_id).account_summary()
    return _context.coolify(account_id).account_summary()


@mcp.tool(title="Search runtime logs", annotations=READ_EXTERNAL)
def observability_search_logs(
    account_id: str,
    start_ms: int,
    end_ms: int,
    filter_expression: str = "",
    limit: int = 100,
    offset: int = 0,
) -> JsonValue:
    """Search runtime logs in a selected SigNoz source."""
    return _context.signoz(account_id).search_logs(
        start_ms=start_ms,
        end_ms=end_ms,
        filter_expression=filter_expression,
        limit=limit,
        offset=offset,
    )


@mcp.tool(title="Search traces", annotations=READ_EXTERNAL)
def observability_search_traces(
    account_id: str,
    start_ms: int,
    end_ms: int,
    filter_expression: str = "",
    limit: int = 100,
    offset: int = 0,
) -> JsonValue:
    """Search traces in a selected SigNoz source."""
    return _context.signoz(account_id).search_traces(
        start_ms=start_ms,
        end_ms=end_ms,
        filter_expression=filter_expression,
        limit=limit,
        offset=offset,
    )


@mcp.tool(title="Query telemetry", annotations=READ_EXTERNAL)
def observability_query_telemetry(account_id: str, query: JsonObject) -> JsonValue:
    """Run a read-only SigNoz Query Builder v5 query for logs, traces or metrics."""
    return _context.signoz(account_id).query_range(query)


@mcp.tool(title="List telemetry services", annotations=READ_EXTERNAL)
def observability_list_services(account_id: str, start: str, end: str) -> JsonValue:
    """List services observed by a selected SigNoz source for a time range."""
    return _context.signoz(account_id).list_services(start=start, end=end)


@mcp.tool(title="Telemetry field keys", annotations=READ_EXTERNAL)
def observability_field_keys(
    account_id: str,
    signal: str,
    search_text: str = "",
    metric_name: str = "",
) -> JsonValue:
    """Discover available SigNoz field keys for logs, traces or metrics."""
    return _context.signoz(account_id).field_keys(
        signal=signal,
        search_text=search_text,
        metric_name=metric_name,
    )


@mcp.tool(title="Telemetry field values", annotations=READ_EXTERNAL)
def observability_field_values(
    account_id: str,
    signal: str,
    name: str,
    search_text: str = "",
    metric_name: str = "",
) -> JsonValue:
    """Discover values for one field in a selected SigNoz source."""
    return _context.signoz(account_id).field_values(
        signal=signal,
        name=name,
        search_text=search_text,
        metric_name=metric_name,
    )


@mcp.tool(title="Infrastructure team", annotations=READ_EXTERNAL)
def observability_current_team(account_id: str) -> JsonObject:
    """Read the current team from a selected Coolify source."""
    return _context.coolify(account_id).current_team()


@mcp.tool(title="List infrastructure servers", annotations=READ_EXTERNAL)
def observability_list_servers(account_id: str) -> JsonValue:
    """List safe server metadata from a selected Coolify source."""
    return _context.coolify(account_id).servers()


@mcp.tool(title="List server resources", annotations=READ_EXTERNAL)
def observability_server_resources(account_id: str, server_uuid: str) -> JsonValue:
    """List safe resource identity/status metadata for one Coolify server."""
    return _context.coolify(account_id).server_resources(server_uuid)


@mcp.tool(title="List infrastructure applications", annotations=READ_EXTERNAL)
def observability_list_applications(account_id: str) -> JsonValue:
    """List applications from a selected Coolify source."""
    return _context.coolify(account_id).applications()


@mcp.tool(title="Infrastructure application", annotations=READ_EXTERNAL)
def observability_get_application(account_id: str, uuid: str) -> JsonObject:
    """Read one application from a selected Coolify source."""
    return _context.coolify(account_id).application(uuid)


@mcp.tool(title="Infrastructure application storages", annotations=READ_EXTERNAL)
def observability_application_storages(account_id: str, application_uuid: str) -> JsonObject:
    """List safe Coolify storage topology without file contents or host filesystem paths."""
    return _context.coolify(account_id).application_storages(application_uuid)


@mcp.tool(title="Infrastructure application variables", annotations=READ_EXTERNAL)
def observability_application_variables(account_id: str, application_uuid: str) -> JsonObject:
    """List safe Coolify application variable metadata; values are never returned."""
    return _context.coolify(account_id).application_variables(application_uuid)


@mcp.tool(title="List infrastructure deployments", annotations=READ_EXTERNAL)
def observability_list_deployments(account_id: str) -> JsonValue:
    """List deployment metadata from a selected Coolify source."""
    return _context.coolify(account_id).deployments()


@mcp.tool(title="List application deployments", annotations=READ_EXTERNAL)
def observability_list_application_deployments(
    account_id: str,
    application_uuid: str,
) -> JsonValue:
    """List deployments for one application in a selected Coolify source."""
    return _context.coolify(account_id).application_deployments(application_uuid)


@mcp.tool(title="Infrastructure deployment", annotations=READ_EXTERNAL)
def observability_get_deployment(account_id: str, uuid: str) -> JsonObject:
    """Read one deployment from a selected Coolify source."""
    return _context.coolify(account_id).deployment(uuid)


app = _runtime_telemetry.attach(private_http_app(mcp, _private))
