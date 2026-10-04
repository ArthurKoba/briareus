from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from common.account_contracts import AccountList, AccountPublic, ResolvedAccount
from common.audit_payloads import redact_payload
from common.cache import CacheBackend, CacheKeys
from common.models import JsonObject, json_object
from common.runtime_policy_contracts import (
    GitHubRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)
from common.settings import ValkeySettings
from management.domain.accounts import Account, Provider
from management.domain.configuration import ManagementConfig
from management.domain.oauth_sessions import OAuthSession
from management.domain.snapshots import CachedSnapshot
from management.domain.telemetry import Invocation

from .ports import (
    AccountRepository,
    ConnectionVerifier,
    CredentialCipher,
    InvocationRepository,
    ManagementConfigRepository,
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
    ) -> None:
        self.repository = repository
        self.cipher = cipher
        self.verifier = verifier
        self.cache = cache
        self.cache_settings = cache_settings or ValkeySettings()
        self.cache_keys = CacheKeys(cache) if cache is not None else None

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

    def list(self, *, provider: Provider | None = None) -> list[AccountPublic]:
        provider_key = provider.value if provider is not None else ""
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_json(self.cache_keys.account_list(provider_key))
            if isinstance(cached, dict):
                return AccountList.model_validate(cached).accounts

        accounts = [
            AccountPublic.model_validate(account.public())
            for account in self.repository.list(provider=provider, enabled_only=False)
        ]
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.account_list(provider_key),
                AccountList(accounts=accounts, count=len(accounts)).to_json(),
                ttl_seconds=self.cache_settings.account_list_ttl_seconds,
            )
        return accounts

    def get(
        self,
        selector: str,
        *,
        provider: Provider,
        enabled_only: bool = True,
    ) -> Account:
        return self.repository.get(selector, provider=provider, enabled_only=enabled_only)

    def resolve(self, selector: str, *, provider: Provider) -> ResolvedAccount:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_json(self.cache_keys.account(provider.value, selector))
            if isinstance(cached, dict):
                return ResolvedAccount.model_validate(cached)

        account = self.repository.get(selector, provider=provider)
        credential = self.cipher.decrypt(self.repository.credential(account.id, provider=provider))
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

    def create(self, account: Account, *, credential: str) -> Account:
        secret = credential.strip()
        if not secret:
            raise ValueError("credential is required")
        saved = self.repository.save(
            account,
            encrypted_credential=self.cipher.encrypt(secret),
        )
        self.invalidate(saved)
        return saved

    def update(
        self,
        account: Account,
        *,
        credential: str = "",
        expected_updated_at: datetime | None = None,
    ) -> Account:
        previous = self.repository.get(account.id, provider=account.provider, enabled_only=False)
        account.updated_at = datetime.now(UTC)
        secret = credential.strip()
        saved = self.repository.save(
            account,
            encrypted_credential=self.cipher.encrypt(secret) if secret else None,
            expected_updated_at=expected_updated_at,
        )
        self.invalidate(previous)
        self.invalidate(saved)
        return saved

    def set_credential(self, account_id: str, credential: str, *, provider: Provider) -> None:
        secret = credential.strip()
        if not secret:
            raise ValueError("credential is required")
        account = self.repository.get(account_id, provider=provider, enabled_only=False)
        self.repository.set_credential(
            account_id,
            self.cipher.encrypt(secret),
            provider=provider,
        )
        self.invalidate(account)

    def delete(self, account_id: str, *, provider: Provider) -> None:
        account = self.repository.get(account_id, provider=provider, enabled_only=False)
        self.repository.delete(account_id, provider=provider)
        self.invalidate(account)

    def verify(self, selector: str, *, provider: Provider) -> JsonObject:
        account = self.repository.get(selector, provider=provider)
        credential = self.cipher.decrypt(self.repository.credential(account.id, provider=provider))
        return json_object(
            self.verifier.verify(account, credential),
            context="connection verification result",
        )

    def verify_candidate(
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
            existing = self.repository.get(
                selector, provider=account.provider, enabled_only=False
            )
            secret = self.cipher.decrypt(
                self.repository.credential(existing.id, provider=account.provider)
            )
        return json_object(
            self.verifier.verify(account, secret),
            context="candidate connection verification result",
        )


class InvocationAuditService:
    def __init__(
        self,
        repository: InvocationRepository,
        config: ManagementConfigService | None = None,
        publisher: Callable[[str, str, object], object] | None = None,
    ) -> None:
        self.repository = repository
        self.config = config
        self.publisher = publisher

    def record(self, invocation: Invocation) -> None:
        self.record_many([invocation])

    def record_many(self, invocations: Sequence[Invocation]) -> None:
        if not invocations:
            return
        capture_payloads = True
        if self.config is not None:
            config = self.config.get()
            if not config.logging_enabled:
                return
            capture_payloads = config.logging_capture_payloads
        self.repository.append_many(invocations, capture_payloads=capture_payloads)
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

    def recent(self, *, limit: int = 100) -> Sequence[Invocation]:
        return self.repository.recent(limit=limit)

    def clear(self) -> int:
        return self.repository.clear()

    def delete(self, invocation_id: str) -> bool:
        return self.repository.delete(invocation_id)

    def summary(self) -> dict[str, int | float]:
        return self.repository.summary()

    def cleanup(self) -> int:
        return self.repository.cleanup()


class OAuthSessionService:
    def __init__(self, repository: OAuthSessionRepository) -> None:
        self.repository = repository

    def record(self, event: object) -> OAuthSession:
        return self.repository.apply_event(event)

    def recent(self, *, limit: int = 200) -> Sequence[OAuthSession]:
        return self.repository.recent(limit=limit)


class SnapshotService:
    def __init__(self, repository: SnapshotRepository) -> None:
        self.repository = repository

    def ensure(
        self,
        key: str,
        *,
        category: str,
        parameters: dict[str, object] | None = None,
        refresh_after_seconds: int,
    ) -> CachedSnapshot:
        return self.repository.ensure(
            key,
            category=category,
            parameters=parameters,
            refresh_after_seconds=refresh_after_seconds,
        )

    def get(self, key: str) -> CachedSnapshot | None:
        return self.repository.get(key)

    def list_category(
        self,
        category: str,
        *,
        limit: int = 1000,
    ) -> Sequence[CachedSnapshot]:
        return self.repository.list_category(category, limit=limit)

    def due(
        self,
        category: str,
        *,
        retry_after_seconds: int = 30,
        limit: int = 100,
    ) -> list[CachedSnapshot]:
        now = datetime.now(UTC)
        result: list[CachedSnapshot] = []
        for snapshot in self.repository.list_category(category, limit=limit):
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

    def mark_attempt(self, key: str) -> None:
        self.repository.mark_attempt(key)

    def store_success(
        self,
        key: str,
        payload: dict[str, object],
    ) -> CachedSnapshot:
        return self.repository.store_success(key, payload)

    def store_error(self, key: str, exc: Exception) -> CachedSnapshot:
        return self.repository.store_error(key, exc)


class ManagementConfigService:
    def __init__(
        self,
        repository: ManagementConfigRepository,
        *,
        cache: CacheBackend | None = None,
        cache_settings: ValkeySettings | None = None,
    ) -> None:
        self.repository = repository
        self.cache = cache
        self.cache_settings = cache_settings or ValkeySettings()
        self.cache_keys = CacheKeys(cache) if cache is not None else None

    def get(self) -> ManagementConfig:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_json(self.cache_keys.management_config())
            if isinstance(cached, dict):
                return ManagementConfig.model_validate(cached)
        result = self.repository.get()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.management_config(),
                result.model_dump(mode="json"),
                ttl_seconds=self.cache_settings.management_config_ttl_seconds,
            )
        return result

    def update(self, config: ManagementConfig) -> ManagementConfig:
        result = self.repository.save(config)
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.management_config(),
                result.model_dump(mode="json"),
                ttl_seconds=self.cache_settings.management_config_ttl_seconds,
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

    def terminal_policy(self) -> TerminalRuntimePolicy:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_json(self.cache_keys.terminal_policy())
            if isinstance(cached, dict):
                return TerminalRuntimePolicy.model_validate(cached)
        result = self.repository.get_terminal_policy()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.terminal_policy(),
                result.to_json(),
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    def update_terminal_policy(
        self,
        policy: TerminalRuntimePolicy,
    ) -> TerminalRuntimePolicy:
        result = self.repository.save_terminal_policy(policy)
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.terminal_policy(),
                result.to_json(),
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    def mcp_policy(self) -> McpRuntimePolicy:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_json(self.cache_keys.mcp_policy())
            if isinstance(cached, dict):
                return McpRuntimePolicy.model_validate(cached)
        result = self.repository.get_mcp_policy()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.mcp_policy(),
                result.to_json(),
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    def update_mcp_policy(self, policy: McpRuntimePolicy) -> McpRuntimePolicy:
        result = self.repository.save_mcp_policy(policy)
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.mcp_policy(),
                result.to_json(),
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    def github_policy(self) -> GitHubRuntimePolicy:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_json(self.cache_keys.github_policy())
            if isinstance(cached, dict):
                return GitHubRuntimePolicy.model_validate(cached)
        result = self.repository.get_github_policy()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.github_policy(),
                result.to_json(),
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    def update_github_policy(self, policy: GitHubRuntimePolicy) -> GitHubRuntimePolicy:
        result = self.repository.save_github_policy(policy)
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_json(
                self.cache_keys.github_policy(),
                result.to_json(),
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result
