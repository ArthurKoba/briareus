from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from admin_api.domain.accounts import Account, Provider
from admin_api.domain.configuration import AdminConfig
from admin_api.domain.oauth_sessions import OAuthSession
from admin_api.domain.snapshots import CachedSnapshot
from admin_api.domain.telemetry import Invocation, InvocationPage, InvocationQuery
from common.runtime_policy_contracts import (
    GitHubRuntimePolicy,
    GitLabRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)


class AccountRepository(Protocol):
    def list(
        self,
        *,
        provider: Provider | None = None,
        enabled_only: bool = True,
    ) -> Sequence[Account]: ...

    def get(
        self,
        selector: str,
        *,
        provider: Provider,
        enabled_only: bool = True,
    ) -> Account: ...

    def save(
        self,
        account: Account,
        *,
        encrypted_credential: str | None = None,
        expected_updated_at: datetime | None = None,
    ) -> Account: ...

    def delete(self, account_id: str, *, provider: Provider) -> None: ...

    def set_credential(
        self,
        account_id: str,
        encrypted_value: str,
        *,
        provider: Provider,
    ) -> None: ...

    def credential(self, account_id: str, *, provider: Provider) -> str: ...


class InvocationRepository(Protocol):
    def append(self, invocation: Invocation, *, capture_payloads: bool = True) -> None: ...

    def append_many(
        self,
        invocations: Sequence[Invocation],
        *,
        capture_payloads: bool = True,
    ) -> None: ...

    def recent(self, *, limit: int = 100) -> Sequence[Invocation]: ...

    def query(self, query: InvocationQuery) -> InvocationPage: ...

    def clear(self) -> int: ...

    def delete(self, invocation_id: str) -> bool: ...

    def summary(self) -> dict[str, int | float]: ...

    def cleanup(self) -> int: ...


class OAuthSessionRepository(Protocol):
    def apply_event(self, event: object) -> OAuthSession: ...

    def recent(self, *, limit: int = 200) -> Sequence[OAuthSession]: ...


class SnapshotRepository(Protocol):
    def ensure(
        self,
        key: str,
        *,
        category: str,
        parameters: dict[str, object] | None = None,
        refresh_after_seconds: int,
    ) -> CachedSnapshot: ...

    def get(self, key: str) -> CachedSnapshot | None: ...

    def list_category(
        self,
        category: str,
        *,
        limit: int = 1000,
    ) -> Sequence[CachedSnapshot]: ...

    def mark_attempt(self, key: str, *, status: str = "refreshing") -> None: ...

    def store_success(
        self,
        key: str,
        payload: dict[str, object],
    ) -> CachedSnapshot: ...

    def store_error(self, key: str, exc: Exception) -> CachedSnapshot: ...


class AdminConfigRepository(Protocol):
    def get(self) -> AdminConfig: ...

    def save(self, config: AdminConfig) -> AdminConfig: ...


class RuntimeSettingsRepository(Protocol):
    def get_terminal_policy(self) -> TerminalRuntimePolicy: ...

    def save_terminal_policy(
        self,
        policy: TerminalRuntimePolicy,
    ) -> TerminalRuntimePolicy: ...

    def get_mcp_policy(self) -> McpRuntimePolicy: ...

    def save_mcp_policy(self, policy: McpRuntimePolicy) -> McpRuntimePolicy: ...

    def get_github_policy(self) -> GitHubRuntimePolicy: ...

    def save_github_policy(self, policy: GitHubRuntimePolicy) -> GitHubRuntimePolicy: ...

    def get_gitlab_policy(self) -> GitLabRuntimePolicy: ...

    def save_gitlab_policy(self, policy: GitLabRuntimePolicy) -> GitLabRuntimePolicy: ...


class CredentialCipher(Protocol):
    def encrypt(self, plaintext: str) -> str: ...

    def decrypt(self, ciphertext: str) -> str: ...


class ConnectionVerifier(Protocol):
    def verify(self, account: Account, credential: str) -> dict[str, object]: ...
