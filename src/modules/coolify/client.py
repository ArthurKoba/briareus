from __future__ import annotations

import ssl
import urllib.error
import urllib.parse
import urllib.request

from common.account_contracts import ResolvedAccount
from common.models import JsonObject, JsonValue, json_loads, json_object


class CoolifyClientError(RuntimeError):
    pass


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
            detail = exc.read()[:4096].decode("utf-8", "replace")
            raise CoolifyClientError(f"Coolify HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise CoolifyClientError(f"Coolify transport error: {exc.reason}") from exc
        return json_loads(raw, context="Coolify response")

    def current_team(self) -> JsonObject:
        return json_object(self._get("/teams/current"), context="Coolify current team")

    def applications(self) -> JsonValue:
        return self._get("/applications")

    def application(self, uuid: str) -> JsonObject:
        return json_object(
            self._get("/applications/" + urllib.parse.quote(uuid, safe="")),
            context="Coolify application",
        )

    def deployments(self) -> JsonValue:
        return self._get("/deployments")

    def deployment(self, uuid: str) -> JsonObject:
        return json_object(
            self._get("/deployments/" + urllib.parse.quote(uuid, safe="")),
            context="Coolify deployment",
        )

    def application_deployments(self, uuid: str) -> JsonValue:
        return self._get("/deployments/applications/" + urllib.parse.quote(uuid, safe=""))

    def account_summary(self) -> JsonObject:
        return json_object(
            {
                **self.account.model_dump(mode="json", exclude={"credential"}),
                "credential_configured": True,
                "permission_contract": "read-only; no sensitive log/env endpoints exposed",
            },
            context="Coolify account summary",
        )
