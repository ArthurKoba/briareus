from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from .account_contracts import AccountList, InvocationEvent, ResolvedAccount
from .cache import CacheBackend, CacheKeys, SharedCache
from .models import JsonObject, json_loads, json_object
from .oauth_session_contracts import OAuthSessionEvent
from .runtime_policy_contracts import McpRuntimePolicy, TerminalRuntimePolicy
from .settings import ManagementClientSettings, ValkeySettings


class ManagementClientError(RuntimeError):
    pass


_TRACER = trace.get_tracer("mcp-bridge.management-client")


class ManagementClient:
    def __init__(
        self,
        settings: ManagementClientSettings,
        *,
        cache: CacheBackend | None = None,
        cache_settings: ValkeySettings | None = None,
    ) -> None:
        self.url = settings.url.rstrip("/")
        self.service_token = settings.service_token
        self.timeout_seconds = settings.timeout_seconds
        if not self.url:
            raise ValueError("MANAGEMENT_URL is required")
        self.cache_settings = cache_settings or ValkeySettings()
        self.cache = cache or SharedCache(self.cache_settings)
        self.cache_keys = CacheKeys(self.cache)

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
        provider_key = (provider or "").strip().casefold()
        cache_key = self.cache_keys.account_list(provider_key)
        cached = self.cache.get_json(cache_key)
        if isinstance(cached, dict):
            return AccountList.model_validate(cached)

        query: dict[str, str] = {}
        if provider:
            query["provider"] = provider
        data = self._request("GET", "/internal/accounts", query=query)
        result = AccountList.model_validate(data)
        self.cache.set_json(
            cache_key,
            result.to_json(),
            ttl_seconds=self.cache_settings.account_list_ttl_seconds,
        )
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
        cache_key = self.cache_keys.account(provider_key, value)
        cached = self.cache.get_json(cache_key)
        if isinstance(cached, dict):
            return ResolvedAccount.model_validate(cached)

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
        payload = account.model_dump(mode="json")
        selectors = {value.casefold(), account.id.casefold(), account.alias.casefold()}
        for resolved_selector in selectors:
            self.cache.set_json(
                self.cache_keys.account(provider_key, resolved_selector),
                payload,
                ttl_seconds=self.cache_settings.account_ttl_seconds,
            )
        return account

    def record_invocation(self, event: InvocationEvent) -> None:
        self._request(
            "POST",
            "/internal/events",
            payload=json_object(event.model_dump(mode="json"), context="invocation event"),
            expect_body=False,
        )

    def terminal_runtime_policy(self) -> TerminalRuntimePolicy:
        cache_key = self.cache_keys.terminal_policy()
        cached = self.cache.get_json(cache_key)
        if isinstance(cached, dict):
            return TerminalRuntimePolicy.model_validate(cached)
        data = self._request("GET", "/internal/runtime-settings/terminal")
        result = TerminalRuntimePolicy.model_validate(data)
        self.cache.set_json(
            cache_key,
            result.to_json(),
            ttl_seconds=self.cache_settings.policy_ttl_seconds,
        )
        return result

    def mcp_runtime_policy(self) -> McpRuntimePolicy:
        cache_key = self.cache_keys.mcp_policy()
        cached = self.cache.get_json(cache_key)
        if isinstance(cached, dict):
            return McpRuntimePolicy.model_validate(cached)
        data = self._request("GET", "/internal/runtime-settings/mcp")
        result = McpRuntimePolicy.model_validate(data)
        self.cache.set_json(
            cache_key,
            result.to_json(),
            ttl_seconds=self.cache_settings.policy_ttl_seconds,
        )
        return result

    def record_oauth_session(self, event: OAuthSessionEvent) -> None:
        self._request(
            "POST",
            "/internal/oauth-sessions/events",
            payload=json_object(event.model_dump(mode="json"), context="oauth session event"),
            expect_body=False,
        )
