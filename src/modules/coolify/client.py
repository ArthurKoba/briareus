from __future__ import annotations

import ssl
import urllib.error
import urllib.parse
import urllib.request

from common.account_contracts import ResolvedAccount
from common.models import JsonObject, JsonValue, json_loads, json_object, json_object_list


class CoolifyClientError(RuntimeError):
    pass


_APPLICATION_FIELDS = (
    "uuid",
    "name",
    "description",
    "status",
    "container_present",
    "server_status",
    "git_repository",
    "git_branch",
    "git_commit_sha",
    "build_pack",
    "dockerfile_location",
    "docker_compose_location",
    "ports_exposes",
    "fqdn",
    "restart_count",
    "restart_limit_reached",
    "last_online_at",
    "last_restart_at",
    "last_restart_type",
    "created_at",
    "updated_at",
)

_DEPLOYMENT_FIELDS = (
    "id",
    "deployment_uuid",
    "application_id",
    "application_name",
    "server_id",
    "server_name",
    "status",
    "commit",
    "commit_message",
    "force_rebuild",
    "restart_only",
    "rollback",
    "pull_request_id",
    "is_api",
    "is_webhook",
    "created_at",
    "updated_at",
    "finished_at",
)

_TEAM_FIELDS = ("id", "name", "description", "personal_team", "created_at", "updated_at")


def _project(payload: JsonObject, fields: tuple[str, ...]) -> JsonObject:
    return {key: payload.get(key) for key in fields if key in payload}


class CoolifyClient:
    def __init__(self, account: ResolvedAccount, *, timeout_seconds: float = 30.0) -> None:
        self.account = account
        self.base_url = account.base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _context(self) -> ssl.SSLContext | None:
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme != "https":
            return None
        if not self.account.verify_tls:
            return ssl._create_unverified_context()
        if self.account.ca_cert_pem:
            return ssl.create_default_context(cadata=self.account.ca_cert_pem.replace("\\n", "\n"))
        return ssl.create_default_context()

    def _get(self, path: str, *, query: dict[str, str] | None = None) -> JsonValue:
        target = self.base_url + "/api/v1" + path
        if query:
            target += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(
            target,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.account.credential}",
                "User-Agent": "mcp-bridge-coolify",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
                context=self._context(),
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            # Never echo arbitrary upstream bodies: Coolify error envelopes can contain secrets.
            raise CoolifyClientError(f"Coolify HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise CoolifyClientError(f"Coolify transport error: {exc.reason}") from exc
        return json_loads(raw, context="Coolify response")

    def current_team(self) -> JsonObject:
        raw = json_object(self._get("/teams/current"), context="Coolify current team")
        return _project(raw, _TEAM_FIELDS)

    def applications(self) -> JsonValue:
        rows = json_object_list(self._get("/applications"), context="Coolify applications")
        return [_project(row, _APPLICATION_FIELDS) for row in rows]

    def application(self, uuid: str) -> JsonObject:
        raw = json_object(
            self._get("/applications/" + urllib.parse.quote(uuid, safe="")),
            context="Coolify application",
        )
        return _project(raw, _APPLICATION_FIELDS)

    def deployments(self) -> JsonValue:
        rows = json_object_list(self._get("/deployments"), context="Coolify deployments")
        return [_project(row, _DEPLOYMENT_FIELDS) for row in rows]

    def deployment(self, uuid: str) -> JsonObject:
        raw = json_object(
            self._get("/deployments/" + urllib.parse.quote(uuid, safe="")),
            context="Coolify deployment",
        )
        return _project(raw, _DEPLOYMENT_FIELDS)

    def application_deployments(self, uuid: str) -> JsonValue:
        rows = json_object_list(
            self._get("/deployments/applications/" + urllib.parse.quote(uuid, safe="")),
            context="Coolify application deployments",
        )
        return [_project(row, _DEPLOYMENT_FIELDS) for row in rows]

    def account_summary(self) -> JsonObject:
        return json_object(
            {
                **self.account.model_dump(mode="json", exclude={"credential"}),
                "credential_configured": True,
                "permission_contract": "read-only; strict safe-field projection",
            },
            context="Coolify account summary",
        )
