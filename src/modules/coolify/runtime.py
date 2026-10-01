from __future__ import annotations

import threading

from common.management_client import ManagementClient
from common.models import JsonObject, JsonValue
from common.runtime_annotations import READ_EXTERNAL
from common.runtime_common import build_private_mcp, management_client, private_http_app
from common.settings import ManagementClientSettings, PrivateRuntimeSettings

from .client import CoolifyClient


class CoolifyRuntimeContext:
    def __init__(self, management: ManagementClient) -> None:
        self.management = management
        self._lock = threading.Lock()
        self._clients: dict[str, tuple[str, CoolifyClient]] = {}

    def accounts(self) -> JsonObject:
        return self.management.list_accounts(provider="coolify").to_json()

    def client(self, account_id: str) -> CoolifyClient:
        account = self.management.resolve_account(account_id, provider="coolify")
        with self._lock:
            cached = self._clients.get(account.id)
            if cached is not None and cached[0] == account.updated_at:
                return cached[1]
            client = CoolifyClient(account)
            self._clients[account.id] = (account.updated_at, client)
            return client


_private = PrivateRuntimeSettings()
_management = management_client(ManagementClientSettings())
_context = CoolifyRuntimeContext(_management)
mcp = build_private_mcp("coolify", _management, observability_scope="coolify")


@mcp.tool(title="Coolify accounts", annotations=READ_EXTERNAL)
def coolify_accounts() -> JsonObject:
    return _context.accounts()


@mcp.tool(title="Coolify connection", annotations=READ_EXTERNAL)
def coolify_connection(account_id: str) -> JsonObject:
    return _context.client(account_id).account_summary()


@mcp.tool(title="Coolify current team", annotations=READ_EXTERNAL)
def coolify_current_team(account_id: str) -> JsonObject:
    return _context.client(account_id).current_team()


@mcp.tool(title="Coolify applications", annotations=READ_EXTERNAL)
def coolify_list_applications(account_id: str) -> JsonValue:
    return _context.client(account_id).applications()


@mcp.tool(title="Coolify application", annotations=READ_EXTERNAL)
def coolify_get_application(account_id: str, uuid: str) -> JsonObject:
    return _context.client(account_id).application(uuid)


@mcp.tool(title="Coolify deployments", annotations=READ_EXTERNAL)
def coolify_list_deployments(account_id: str) -> JsonValue:
    return _context.client(account_id).deployments()


@mcp.tool(title="Coolify application deployments", annotations=READ_EXTERNAL)
def coolify_list_application_deployments(account_id: str, application_uuid: str) -> JsonValue:
    return _context.client(account_id).application_deployments(application_uuid)


@mcp.tool(title="Coolify deployment", annotations=READ_EXTERNAL)
def coolify_get_deployment(account_id: str, uuid: str) -> JsonObject:
    return _context.client(account_id).deployment(uuid)


app = private_http_app(mcp, _private)
