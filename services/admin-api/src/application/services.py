from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from domain.accounts import Account, Provider
from domain.configuration import AdminConfig
from domain.oauth_sessions import OAuthSession
from domain.snapshots import CachedSnapshot
from domain.telemetry import Invocation, InvocationPage, InvocationQuery

from common.account_contracts import AccountList, AccountPublic, ResolvedAccount
from common.audit_payloads import redact_payload
from common.cache import CacheBackend, CacheKeys
from common.models import JsonObject, json_object
from common.runtime_policy_contracts import (
    GitHubRuntimePolicy,
    GitLabRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)
from common.settings import ValkeySettings

from .ports import (
    AccountRepository,
    AdminConfigRepository,
    ConnectionVerifier,
    CredentialCipher,
    InvocationRepository,
    OAuthSessionRepository,
    RuntimeSettingsRepository,
    SnapshotRepository,
)


class AccountService:
    def __init__(
        self,
        repository: AccountRepository,
        cipher: CredentialCipher,
        verifier: ConnectionVerifier,
        *,
        cache: CacheBackend | None = None,
        cache_settings: ValkeySettings | None = None,
        publisher: Callable[[str, str, object], object] | None = None,
    ) -> None:
        self.repository = repository
        self.cipher = cipher
        self.verifier = verifier
        self.cache = cache
        self.cache_settings = cache_settings or ValkeySettings()
        self.cache_keys = CacheKeys(cache) if cache is not None else None
        self.publisher = publisher

    def publish(self, event_type: str, data: object) -> None:
        if self.publisher is not None:
            self.publisher("admin.events", event_type, data)

    def invalidate(self, account: Account) -> None:
        if self.cache is None or self.cache_keys is None:
            return
        self.cache.delete(
            *self.cache_keys.account_invalidation_keys(
                account.provider.value,
                account_id=account.id,
                alias=account.alias,
            )
        )

    async def list(self, *, provider: Provider | None = None) -> list[AccountPublic]:
        provider_key = provider.value if provider is not None else ""
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_json(self.cache_keys.account_list(provider_key))
            if isinstance(cached, dict):
                return AccountList.model_validate(cached).accounts

        accounts = [
            AccountPublic.model_validate(account.public())
            for account in await self.repository.list(provider=provider, enabled_only=False)
        ]
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.account_list(provider_key),
                AccountList(accounts=accounts, count=len(accounts)).to_json(),
                ttl_seconds=self.cache_settings.account_list_ttl_seconds,
            )
        return accounts

    async def get(
        self,
        selector: str,
        *,
        provider: Provider,
        enabled_only: bool = True,
    ) -> Account:
        return await self.repository.get(selector, provider=provider, enabled_only=enabled_only)

    async def resolve(self, selector: str, *, provider: Provider) -> ResolvedAccount:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_json(self.cache_keys.account(provider.value, selector))
            if isinstance(cached, dict):
                return ResolvedAccount.model_validate(cached)

        account = await self.repository.get(selector, provider=provider)
        credential = self.cipher.decrypt(
            await self.repository.credential(account.id, provider=provider)
        )
        resolved = ResolvedAccount.model_validate({**account.public(), "credential": credential})
        if self.cache is not None and self.cache_keys is not None:
            payload = resolved.model_dump(mode="json")
            selectors = {selector.casefold(), account.id.casefold(), account.alias.casefold()}
            for resolved_selector in selectors:
                self.cache.set_json(
                    self.cache_keys.account(provider.value, resolved_selector),
                    payload,
                    ttl_seconds=self.cache_settings.account_ttl_seconds,
                )
        return resolved

    async def create(self, account: Account, *, credential: str) -> Account:
        secret = credential.strip()
        if not secret:
            raise ValueError("credential is required")
        saved = await self.repository.save(
            account,
            encrypted_credential=self.cipher.encrypt(secret),
        )
        self.invalidate(saved)
        self.publish("account.created", saved.public())
        return saved

    async def update(
        self,
        account: Account,
        *,
        credential: str = "",
        expected_updated_at: datetime | None = None,
    ) -> Account:
        previous = await self.repository.get(
            account.id, provider=account.provider, enabled_only=False
        )
        account.updated_at = datetime.now(UTC)
        secret = credential.strip()
        saved = await self.repository.save(
            account,
            encrypted_credential=self.cipher.encrypt(secret) if secret else None,
            expected_updated_at=expected_updated_at,
        )
        self.invalidate(previous)
        self.invalidate(saved)
        self.publish("account.updated", saved.public())
        return saved

    async def set_credential(self, account_id: str, credential: str, *, provider: Provider) -> None:
        secret = credential.strip()
        if not secret:
            raise ValueError("credential is required")
        account = await self.repository.get(account_id, provider=provider, enabled_only=False)
        await self.repository.set_credential(
            account_id,
            self.cipher.encrypt(secret),
            provider=provider,
        )
        updated = await self.repository.get(account_id, provider=provider, enabled_only=False)
        self.invalidate(account)
        self.invalidate(updated)
        self.publish("account.updated", updated.public())

    async def delete(self, account_id: str, *, provider: Provider) -> None:
        account = await self.repository.get(account_id, provider=provider, enabled_only=False)
        await self.repository.delete(account_id, provider=provider)
        self.invalidate(account)
        self.publish("account.deleted", {"id": account.id, "provider": account.provider.value})

    async def verify(self, selector: str, *, provider: Provider) -> JsonObject:
        account = await self.repository.get(selector, provider=provider)
        credential = self.cipher.decrypt(
            await self.repository.credential(account.id, provider=provider)
        )
        result = json_object(
            await asyncio.to_thread(self.verifier.verify, account, credential),
            context="connection verification result",
        )
        self.publish(
            "account.verified",
            {"id": account.id, "provider": account.provider.value, "ok": result.get("ok") is True},
        )
        return result

    async def verify_candidate(
        self,
        account: Account,
        *,
        credential: str = "",
        credential_account_id: str = "",
    ) -> JsonObject:
        secret = credential.strip()
        if not secret:
            selector = credential_account_id.strip()
            if not selector:
                raise ValueError("credential is required for a new account")
            existing = await self.repository.get(
                selector, provider=account.provider, enabled_only=False
            )
            secret = self.cipher.decrypt(
                await self.repository.credential(existing.id, provider=account.provider)
            )
        return json_object(
            await asyncio.to_thread(self.verifier.verify, account, secret),
            context="candidate connection verification result",
        )


class InvocationAuditService:
    def __init__(
        self,
        repository: InvocationRepository,
        config: AdminConfigService | None = None,
        publisher: Callable[[str, str, object], object] | None = None,
    ) -> None:
        self.repository = repository
        self.config = config
        self.publisher = publisher

    async def record(self, invocation: Invocation) -> None:
        await self.record_many([invocation])

    async def record_many(self, invocations: Sequence[Invocation]) -> None:
        if not invocations:
            return
        capture_payloads = True
        if self.config is not None:
            config = await self.config.get()
            if not config.logging_enabled:
                return
            capture_payloads = config.logging_capture_payloads
        await self.repository.append_many(invocations, capture_payloads=capture_payloads)
        if self.publisher is not None:
            events: list[object] = []
            for item in invocations:
                event = item.model_dump(mode="json")
                if not capture_payloads:
                    event["arguments_json"] = ""
                    event["result_json"] = ""
                    event["error_message"] = ""
                events.append(redact_payload(event))
            self.publisher(
                "mcp.calls",
                "batch",
                {"events": events, "count": len(events)},
            )

    async def recent(self, *, limit: int = 100) -> Sequence[Invocation]:
        return await self.repository.recent(limit=limit)

    async def query(self, query: InvocationQuery) -> InvocationPage:
        return await self.repository.query(query)

    async def clear(self) -> int:
        return await self.repository.clear()

    async def delete(self, invocation_id: str) -> bool:
        return await self.repository.delete(invocation_id)

    async def summary(self) -> dict[str, int | float]:
        return await self.repository.summary()

    async def cleanup(self) -> int:
        return await self.repository.cleanup()


class OAuthSessionService:
    def __init__(self, repository: OAuthSessionRepository) -> None:
        self.repository = repository

    async def record(self, event: object) -> OAuthSession:
        return await self.repository.apply_event(event)

    async def recent(self, *, limit: int = 200) -> Sequence[OAuthSession]:
        return await self.repository.recent(limit=limit)


class SnapshotService:
    def __init__(self, repository: SnapshotRepository) -> None:
        self.repository = repository

    async def ensure(
        self,
        key: str,
        *,
        category: str,
        parameters: dict[str, object] | None = None,
        refresh_after_seconds: int,
    ) -> CachedSnapshot:
        return await self.repository.ensure(
            key,
            category=category,
            parameters=parameters,
            refresh_after_seconds=refresh_after_seconds,
        )

    async def get(self, key: str) -> CachedSnapshot | None:
        return await self.repository.get(key)

    async def list_category(
        self,
        category: str,
        *,
        limit: int = 1000,
    ) -> Sequence[CachedSnapshot]:
        return await self.repository.list_category(category, limit=limit)

    async def due(
        self,
        category: str,
        *,
        retry_after_seconds: int = 30,
        limit: int = 100,
    ) -> list[CachedSnapshot]:
        now = datetime.now(UTC)
        result: list[CachedSnapshot] = []
        for snapshot in await self.repository.list_category(category, limit=limit):
            if snapshot.status == "refreshing":
                attempted = snapshot.attempted_at
                if attempted is not None and attempted.tzinfo is None:
                    attempted = attempted.replace(tzinfo=UTC)
                if (
                    attempted is not None
                    and (now - attempted).total_seconds() < retry_after_seconds
                ):
                    continue
            attempted = snapshot.attempted_at
            if attempted is not None and attempted.tzinfo is None:
                attempted = attempted.replace(tzinfo=UTC)
            if snapshot.stale(now) and (
                attempted is None or (now - attempted).total_seconds() >= retry_after_seconds
            ):
                result.append(snapshot)
        return result

    async def mark_attempt(self, key: str) -> None:
        await self.repository.mark_attempt(key)

    async def store_success(
        self,
        key: str,
        payload: dict[str, object],
    ) -> CachedSnapshot:
        return await self.repository.store_success(key, payload)

    async def store_error(self, key: str, exc: Exception) -> CachedSnapshot:
        return await self.repository.store_error(key, exc)


class AdminConfigService:
    def __init__(
        self,
        repository: AdminConfigRepository,
        *,
        cache: CacheBackend | None = None,
        cache_settings: ValkeySettings | None = None,
    ) -> None:
        self.repository = repository
        self.cache = cache
        self.cache_settings = cache_settings or ValkeySettings()
        self.cache_keys = CacheKeys(cache) if cache is not None else None

    async def get(self) -> AdminConfig:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_json(self.cache_keys.admin_config())
            if isinstance(cached, dict):
                return AdminConfig.model_validate(cached)
        result = await self.repository.get()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.admin_config(),
                result.model_dump(mode="json"),
                ttl_seconds=self.cache_settings.admin_config_ttl_seconds,
            )
        return result

    async def update(self, config: AdminConfig) -> AdminConfig:
        result = await self.repository.save(config)
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.admin_config(),
                result.model_dump(mode="json"),
                ttl_seconds=self.cache_settings.admin_config_ttl_seconds,
            )
        return result


class RuntimeSettingsService:
    def __init__(
        self,
        repository: RuntimeSettingsRepository,
        *,
        cache: CacheBackend | None = None,
        cache_settings: ValkeySettings | None = None,
    ) -> None:
        self.repository = repository
        self.cache = cache
        self.cache_settings = cache_settings or ValkeySettings()
        self.cache_keys = CacheKeys(cache) if cache is not None else None

    async def terminal_policy(self) -> TerminalRuntimePolicy:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_json(self.cache_keys.terminal_policy())
            if isinstance(cached, dict):
                return TerminalRuntimePolicy.model_validate(cached)
        result = await self.repository.get_terminal_policy()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.terminal_policy(),
                result.to_json(),
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def update_terminal_policy(
        self,
        policy: TerminalRuntimePolicy,
    ) -> TerminalRuntimePolicy:
        result = await self.repository.save_terminal_policy(policy)
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.terminal_policy(),
                result.to_json(),
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def mcp_policy(self) -> McpRuntimePolicy:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_json(self.cache_keys.mcp_policy())
            if isinstance(cached, dict):
                return McpRuntimePolicy.model_validate(cached)
        result = await self.repository.get_mcp_policy()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.mcp_policy(),
                result.to_json(),
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def update_mcp_policy(self, policy: McpRuntimePolicy) -> McpRuntimePolicy:
        result = await self.repository.save_mcp_policy(policy)
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.mcp_policy(),
                result.to_json(),
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def github_policy(self) -> GitHubRuntimePolicy:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_json(self.cache_keys.github_policy())
            if isinstance(cached, dict):
                return GitHubRuntimePolicy.model_validate(cached)
        result = await self.repository.get_github_policy()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.github_policy(),
                result.to_json(),
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def update_github_policy(self, policy: GitHubRuntimePolicy) -> GitHubRuntimePolicy:
        result = await self.repository.save_github_policy(policy)
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.github_policy(),
                result.to_json(),
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def gitlab_policy(self) -> GitLabRuntimePolicy:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_json(self.cache_keys.gitlab_policy())
            if isinstance(cached, dict):
                return GitLabRuntimePolicy.model_validate(cached)
        result = await self.repository.get_gitlab_policy()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.gitlab_policy(),
                result.to_json(),
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def update_gitlab_policy(self, policy: GitLabRuntimePolicy) -> GitLabRuntimePolicy:
        result = await self.repository.save_gitlab_policy(policy)
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.gitlab_policy(),
                result.to_json(),
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result
