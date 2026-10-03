from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from .account_contracts import AccountList, InvocationEvent, ResolvedAccount
from .models import JsonObject, json_loads, json_object
from .oauth_session_contracts import OAuthSessionEvent
from .runtime_policy_contracts import McpRuntimePolicy, TerminalRuntimePolicy
from .settings import ManagementClientSettings


class ManagementClientError(RuntimeError):
    pass


_TRACER = trace.get_tracer("mcp-bridge.management-client")
_ACCOUNT_CACHE_TTL_SECONDS = 30.0
_ACCOUNT_LIST_CACHE_TTL_SECONDS = 15.0
_POLICY_CACHE_TTL_SECONDS = 30.0


class ManagementClient:
    def __init__(self, settings: ManagementClientSettings) -> None:
        self.url = settings.url.rstrip("/")
        self.service_token = settings.service_token
        self.timeout_seconds = settings.timeout_seconds
        if not self.url:
            raise ValueError("MANAGEMENT_URL is required")
        self._cache_lock = threading.Lock()
        self._account_cache: dict[tuple[str, str], tuple[float, ResolvedAccount]] = {}
        self._account_list_cache: dict[str, tuple[float, AccountList]] = {}
        self._terminal_policy_cache: tuple[float, TerminalRuntimePolicy] | None = None
        self._mcp_policy_cache: tuple[float, McpRuntimePolicy] | None = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: JsonObject | None = None,
        expect_body: bool = True,
    ) -> JsonObject:
        target = self.url + path
        if query:
            target += "?" + urllib.parse.urlencode(query)
        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.service_token}",
            "User-Agent": "mcp-bridge",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(target, data=body, method=method, headers=headers)
        with _TRACER.start_as_current_span(
            "management.http",
            kind=SpanKind.CLIENT,
            attributes={
                "http.request.method": method,
                "url.path": path,
            },
        ):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read()
            except urllib.error.HTTPError as exc:
                detail = exc.read()[:2048].decode("utf-8", "replace")
                raise ManagementClientError(f"management HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                raise ManagementClientError(f"management transport error: {exc.reason}") from exc
        if not expect_body or not raw:
            return {}
        return json_object(
            json_loads(raw, context="management response"),
            context="management response",
        )

    def list_accounts(
        self,
        *,
        provider: str | None = None,
    ) -> AccountList:
        key = (provider or "").strip().casefold()
        now = time.monotonic()
        with self._cache_lock:
            cached = self._account_list_cache.get(key)
            if cached is not None and cached[0] > now:
                trace.get_current_span().set_attribute(
                    "mcp.management.account_list_cache_hit", True
                )
                return cached[1]
        trace.get_current_span().set_attribute(
            "mcp.management.account_list_cache_hit", False
        )
        query: dict[str, str] = {}
        if provider:
            query["provider"] = provider
        data = self._request("GET", "/internal/accounts", query=query)
        result = AccountList.model_validate(data)
        with self._cache_lock:
            self._account_list_cache[key] = (now + _ACCOUNT_LIST_CACHE_TTL_SECONDS, result)
        return result

    def resolve_account(
        self,
        selector: str,
        *,
        provider: str,
    ) -> ResolvedAccount:
        value = selector.strip()
        if not value:
            raise ValueError("account_id is required")
        provider_key = provider.strip().casefold()
        cache_key = (provider_key, value.casefold())
        now = time.monotonic()
        with self._cache_lock:
            cached = self._account_cache.get(cache_key)
            if cached is not None and cached[0] > now:
                trace.get_current_span().set_attribute("mcp.management.account_cache_hit", True)
                return cached[1]
        trace.get_current_span().set_attribute("mcp.management.account_cache_hit", False)
        query = {"provider": provider}
        path = "/internal/accounts/" + urllib.parse.quote(value, safe="") + "/resolve"
        try:
            data = self._request("GET", path, query=query)
        except ManagementClientError as exc:
            if "management HTTP 404:" not in str(exc):
                raise
            accounts = self.list_accounts(provider=provider)
            aliases = sorted(account.alias for account in accounts.accounts if account.alias)
            hint = f"; use stable account alias instead: {', '.join(aliases)}" if aliases else ""
            raise ManagementClientError(
                f"{provider} account selector not found: {value}{hint}"
            ) from exc
        account = ResolvedAccount.model_validate(data)
        expires_at = now + _ACCOUNT_CACHE_TTL_SECONDS
        keys = {value.casefold(), account.id.casefold(), account.alias.casefold()}
        with self._cache_lock:
            for selector in keys:
                self._account_cache[(provider_key, selector)] = (expires_at, account)
        return account

    def record_invocation(self, event: InvocationEvent) -> None:
        self._request(
            "POST",
            "/internal/events",
            payload=json_object(event.model_dump(mode="json"), context="invocation event"),
            expect_body=False,
        )

    def terminal_runtime_policy(self) -> TerminalRuntimePolicy:
        now = time.monotonic()
        with self._cache_lock:
            cached = self._terminal_policy_cache
            if cached is not None and cached[0] > now:
                trace.get_current_span().set_attribute(
                    "mcp.management.terminal_policy_cache_hit", True
                )
                return cached[1]
        trace.get_current_span().set_attribute(
            "mcp.management.terminal_policy_cache_hit", False
        )
        data = self._request("GET", "/internal/runtime-settings/terminal")
        result = TerminalRuntimePolicy.model_validate(data)
        with self._cache_lock:
            self._terminal_policy_cache = (now + _POLICY_CACHE_TTL_SECONDS, result)
        return result

    def mcp_runtime_policy(self) -> McpRuntimePolicy:
        now = time.monotonic()
        with self._cache_lock:
            cached = self._mcp_policy_cache
            if cached is not None and cached[0] > now:
                trace.get_current_span().set_attribute("mcp.management.mcp_policy_cache_hit", True)
                return cached[1]
        trace.get_current_span().set_attribute("mcp.management.mcp_policy_cache_hit", False)
        data = self._request("GET", "/internal/runtime-settings/mcp")
        result = McpRuntimePolicy.model_validate(data)
        with self._cache_lock:
            self._mcp_policy_cache = (now + _POLICY_CACHE_TTL_SECONDS, result)
        return result

    def record_oauth_session(self, event: OAuthSessionEvent) -> None:
        self._request(
            "POST",
            "/internal/oauth-sessions/events",
            payload=json_object(event.model_dump(mode="json"), context="oauth session event"),
            expect_body=False,
        )
