from __future__ import annotations

import http.client
import ssl
import urllib.parse

from common.account_contracts import ResolvedAccount
from common.http_transport import HttpTransportError, PooledHttpTransport
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
    "base_directory",
    "environment_id",
    "destination_id",
    "source_id",
    "compose_parsing_version",
    "is_raw_compose_deployment_enabled",
    "include_source_commit_in_build",
    "inject_build_args_to_dockerfile",
    "disable_build_cache",
    "is_git_shallow_clone_enabled",
    "is_git_submodules_enabled",
    "is_git_lfs_enabled",
    "watch_paths",
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

_SERVER_FIELDS = (
    "uuid",
    "name",
    "description",
    "proxy_type",
    "server_role",
    "unreachable_count",
    "created_at",
    "updated_at",
)

_SERVER_RESOURCE_FIELDS = (
    "uuid",
    "name",
    "type",
    "status",
    "created_at",
    "updated_at",
)

_STORAGE_FIELDS = (
    "uuid",
    "name",
    "mount_path",
    "is_directory",
    "created_at",
    "updated_at",
)


_ENVIRONMENT_METADATA_FIELDS = (
    "uuid",
    "key",
    "is_preview",
    "is_runtime",
    "is_buildtime",
    "is_shared",
    "is_shown_once",
    "is_literal",
    "is_multiline",
    "version",
    "created_at",
    "updated_at",
)


def _project(payload: JsonObject, fields: tuple[str, ...]) -> JsonObject:
    return {key: payload.get(key) for key in fields if key in payload}


class CoolifyClient:
    def __init__(self, account: ResolvedAccount, *, timeout_seconds: float = 30.0) -> None:
        self.account = account
        self.base_url = account.base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise CoolifyClientError("Coolify base_url must be absolute HTTP(S)")
        self._scheme = parsed.scheme
        self._hostname = parsed.hostname
        self._port = parsed.port
        self._base_path = parsed.path.rstrip("/")
        self._transport = PooledHttpTransport(
            self._new_connection,
            max_connections=4,
            acquire_timeout=self.timeout_seconds,
            span_name="provider.coolify.http",
            provider="coolify",
        )

    def _context(self) -> ssl.SSLContext | None:
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme != "https":
            return None
        if not self.account.verify_tls:
            return ssl._create_unverified_context()
        if self.account.ca_cert_pem:
            return ssl.create_default_context(cadata=self.account.ca_cert_pem.replace("\\n", "\n"))
        return ssl.create_default_context()

    def _new_connection(self) -> http.client.HTTPConnection:
        if self._scheme == "https":
            return http.client.HTTPSConnection(
                self._hostname,
                self._port,
                timeout=self.timeout_seconds,
                context=self._context(),
            )
        return http.client.HTTPConnection(
            self._hostname,
            self._port,
            timeout=self.timeout_seconds,
        )

    def _target(self, path: str, query: dict[str, str] | None = None) -> str:
        if not path.startswith("/"):
            raise CoolifyClientError("Coolify path must start with /")
        target = self._base_path + "/api/v1" + path
        if query:
            target += "?" + urllib.parse.urlencode(query)
        return target

    def _get(self, path: str, *, query: dict[str, str] | None = None) -> JsonValue:
        try:
            response = self._transport.request(
                "GET",
                self._target(path, query),
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.account.credential}",
                    "User-Agent": "mcp-bridge-coolify",
                },
                reconnect_retries=1,
            )
        except HttpTransportError as exc:
            raise CoolifyClientError(f"Coolify transport error: {exc}") from exc
        if response.status >= 400:
            raise CoolifyClientError(f"Coolify HTTP {response.status}")
        return json_loads(response.body, context="Coolify response")

    def current_team(self) -> JsonObject:
        raw = json_object(self._get("/teams/current"), context="Coolify current team")
        return _project(raw, _TEAM_FIELDS)

    def servers(self) -> JsonValue:
        rows = json_object_list(self._get("/servers"), context="Coolify servers")
        return [_project(row, _SERVER_FIELDS) for row in rows]

    def server_resources(self, uuid: str) -> JsonValue:
        rows = json_object_list(
            self._get("/servers/" + urllib.parse.quote(uuid, safe="") + "/resources"),
            context="Coolify server resources",
        )
        return [_project(row, _SERVER_RESOURCE_FIELDS) for row in rows]

    def applications(self) -> JsonValue:
        rows = json_object_list(self._get("/applications"), context="Coolify applications")
        return [_project(row, _APPLICATION_FIELDS) for row in rows]

    def application(self, uuid: str) -> JsonObject:
        raw = json_object(
            self._get("/applications/" + urllib.parse.quote(uuid, safe="")),
            context="Coolify application",
        )
        return _project(raw, _APPLICATION_FIELDS)

    def application_storages(self, uuid: str) -> JsonObject:
        """Return safe persistent/file storage metadata without file contents or host paths."""
        envelope = json_object(
            self._get("/applications/" + urllib.parse.quote(uuid, safe="") + "/storages"),
            context="Coolify application storages",
        )
        persistent_rows = json_object_list(
            envelope.get("persistent_storages"),
            context="Coolify application storages.persistent_storages",
        )
        file_rows = json_object_list(
            envelope.get("file_storages"),
            context="Coolify application storages.file_storages",
        )
        persistent: list[JsonValue] = [
            {**_project(row, _STORAGE_FIELDS), "type": "persistent"}
            for row in persistent_rows
        ]
        files: list[JsonValue] = [
            {**_project(row, _STORAGE_FIELDS), "type": "file"} for row in file_rows
        ]
        return {
            "application_uuid": uuid,
            "persistent_storages": persistent,
            "file_storages": files,
            "count": len(persistent) + len(files),
            "contents_exposed": False,
            "host_paths_exposed": False,
        }

    def application_variables(self, uuid: str) -> JsonObject:
        """Return environment-variable metadata without exposing any values."""
        rows = json_object_list(
            self._get(
                "/applications/" + urllib.parse.quote(uuid, safe="") + "/envs"
            ),
            context="Coolify application environment variables",
        )
        variables: list[JsonObject] = [
            _project(row, _ENVIRONMENT_METADATA_FIELDS) for row in rows
        ]
        variables.sort(key=lambda item: str(item.get("key") or "").casefold())
        variables_json: list[JsonValue] = list(variables)
        return {
            "application_uuid": uuid,
            "variables": variables_json,
            "count": len(variables),
            "values_exposed": False,
        }

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
        envelope = json_object(
            self._get("/deployments/applications/" + urllib.parse.quote(uuid, safe="")),
            context="Coolify application deployments",
        )
        rows = json_object_list(
            envelope.get("deployments"),
            context="Coolify application deployments.deployments",
        )
        return {
            "deployments": [_project(row, _DEPLOYMENT_FIELDS) for row in rows],
            "count": len(rows),
        }

    def account_summary(self) -> JsonObject:
        return json_object(
            {
                **self.account.model_dump(mode="json", exclude={"credential"}),
                "credential_configured": True,
                "permission_contract": "read-only; strict safe-field projection",
            },
            context="Coolify account summary",
        )
