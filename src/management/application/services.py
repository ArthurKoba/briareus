from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from common.account_contracts import AccountPublic, ResolvedAccount
from common.models import JsonObject, json_object
from common.runtime_policy_contracts import McpRuntimePolicy, TerminalRuntimePolicy
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
    ) -> None:
        self.repository = repository
        self.cipher = cipher
        self.verifier = verifier

    def list(self, *, provider: Provider | None = None) -> list[AccountPublic]:
        return [
            AccountPublic.model_validate(account.public())
            for account in self.repository.list(provider=provider, enabled_only=False)
        ]

    def get(self, selector: str, *, provider: Provider) -> Account:
        return self.repository.get(selector, provider=provider)

    def resolve(self, selector: str, *, provider: Provider) -> ResolvedAccount:
        account = self.repository.get(selector, provider=provider)
        credential = self.cipher.decrypt(self.repository.credential(account.id, provider=provider))
        return ResolvedAccount.model_validate({**account.public(), "credential": credential})

    def create(self, account: Account, *, credential: str) -> Account:
        secret = credential.strip()
        if not secret:
            raise ValueError("credential is required")
        return self.repository.save(
            account,
            encrypted_credential=self.cipher.encrypt(secret),
        )

    def update(self, account: Account) -> Account:
        account.updated_at = datetime.now(UTC)
        return self.repository.save(account)

    def set_credential(self, account_id: str, credential: str, *, provider: Provider) -> None:
        secret = credential.strip()
        if not secret:
            raise ValueError("credential is required")
        self.repository.set_credential(
            account_id,
            self.cipher.encrypt(secret),
            provider=provider,
        )

    def delete(self, account_id: str, *, provider: Provider) -> None:
        self.repository.delete(account_id, provider=provider)

    def verify(self, selector: str, *, provider: Provider) -> JsonObject:
        account = self.repository.get(selector, provider=provider)
        credential = self.cipher.decrypt(self.repository.credential(account.id, provider=provider))
        return json_object(
            self.verifier.verify(account, credential),
            context="connection verification result",
        )


class InvocationAuditService:
    def __init__(self, repository: InvocationRepository) -> None:
        self.repository = repository

    def record(self, invocation: Invocation) -> None:
        self.repository.append(invocation)

    def recent(self, *, limit: int = 100) -> Sequence[Invocation]:
        return self.repository.recent(limit=limit)

    def clear(self) -> int:
        return self.repository.clear()

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
    def __init__(self, repository: ManagementConfigRepository) -> None:
        self.repository = repository

    def get(self) -> ManagementConfig:
        return self.repository.get()

    def update(self, config: ManagementConfig) -> ManagementConfig:
        return self.repository.save(config)


class RuntimeSettingsService:
    def __init__(self, repository: RuntimeSettingsRepository) -> None:
        self.repository = repository

    def terminal_policy(self) -> TerminalRuntimePolicy:
        return self.repository.get_terminal_policy()

    def update_terminal_policy(
        self,
        policy: TerminalRuntimePolicy,
    ) -> TerminalRuntimePolicy:
        return self.repository.save_terminal_policy(policy)

    def mcp_policy(self) -> McpRuntimePolicy:
        return self.repository.get_mcp_policy()

    def update_mcp_policy(self, policy: McpRuntimePolicy) -> McpRuntimePolicy:
        return self.repository.save_mcp_policy(policy)
