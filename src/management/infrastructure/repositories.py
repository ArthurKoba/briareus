from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import delete, func, or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from management.domain.accounts import Account, AuthType, Provider
from management.domain.configuration import ManagementConfig
from management.domain.telemetry import Invocation

from .database import (
    GitHubAccountRecord,
    GitLabAccountRecord,
    InvocationRecord,
    ManagementConfigRecord,
)


class SqlAlchemyAccountRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    @staticmethod
    def _github_domain(record: GitHubAccountRecord) -> Account:
        return Account(
            id=record.id,
            alias=record.alias,
            provider=Provider.GITHUB,
            auth_type=AuthType(record.auth_type),
            base_url="https://api.github.com",
            external_id=record.app_id,
            verify_tls=True,
            ca_cert_pem="",
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _gitlab_domain(record: GitLabAccountRecord) -> Account:
        return Account(
            id=record.id,
            alias=record.alias,
            provider=Provider.GITLAB,
            auth_type=AuthType(record.auth_type),
            base_url=record.base_url,
            external_id="",
            verify_tls=record.verify_tls,
            ca_cert_pem=record.ca_cert_pem,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def list(
        self,
        *,
        provider: Provider | None = None,
        enabled_only: bool = True,
    ) -> Sequence[Account]:
        accounts: list[Account] = []
        with self.sessions() as session:
            if provider in {None, Provider.GITHUB}:
                github_stmt = select(GitHubAccountRecord)
                if enabled_only:
                    github_stmt = github_stmt.where(GitHubAccountRecord.enabled.is_(True))
                accounts.extend(
                    self._github_domain(row)
                    for row in session.scalars(github_stmt).all()
                )
            if provider in {None, Provider.GITLAB}:
                gitlab_stmt = select(GitLabAccountRecord)
                if enabled_only:
                    gitlab_stmt = gitlab_stmt.where(GitLabAccountRecord.enabled.is_(True))
                accounts.extend(
                    self._gitlab_domain(row)
                    for row in session.scalars(gitlab_stmt).all()
                )
        return sorted(accounts, key=lambda item: (item.provider.value, item.alias))

    def get(
        self,
        selector: str,
        *,
        provider: Provider,
        enabled_only: bool = True,
    ) -> Account:
        value = selector.strip()
        if not value:
            raise KeyError("account selector is required")
        with self.sessions() as session:
            if provider is Provider.GITHUB:
                github_stmt = select(GitHubAccountRecord).where(
                    or_(
                        GitHubAccountRecord.id == value,
                        GitHubAccountRecord.alias == value.casefold(),
                    )
                )
                if enabled_only:
                    github_stmt = github_stmt.where(GitHubAccountRecord.enabled.is_(True))
                github_record = session.scalar(github_stmt)
                if github_record is None:
                    raise KeyError(f"GitHub account not found: {selector}")
                return self._github_domain(github_record)

            gitlab_stmt = select(GitLabAccountRecord).where(
                or_(
                    GitLabAccountRecord.id == value,
                    GitLabAccountRecord.alias == value.casefold(),
                )
            )
            if enabled_only:
                gitlab_stmt = gitlab_stmt.where(GitLabAccountRecord.enabled.is_(True))
            gitlab_record = session.scalar(gitlab_stmt)
            if gitlab_record is None:
                raise KeyError(f"GitLab account not found: {selector}")
            return self._gitlab_domain(gitlab_record)

    def save(self, account: Account, *, encrypted_credential: str | None = None) -> Account:
        with self.sessions.begin() as session:
            if account.provider is Provider.GITHUB:
                github_record = session.get(GitHubAccountRecord, account.id)
                if github_record is None:
                    github_record = GitHubAccountRecord(id=account.id)
                    session.add(github_record)
                github_record.alias = account.alias
                github_record.auth_type = account.auth_type.value
                github_record.app_id = account.external_id
                github_record.enabled = account.enabled
                github_record.created_at = account.created_at
                github_record.updated_at = account.updated_at
                if encrypted_credential is not None:
                    github_record.encrypted_credential = encrypted_credential
            else:
                gitlab_record = session.get(GitLabAccountRecord, account.id)
                if gitlab_record is None:
                    gitlab_record = GitLabAccountRecord(id=account.id)
                    session.add(gitlab_record)
                gitlab_record.alias = account.alias
                gitlab_record.auth_type = account.auth_type.value
                gitlab_record.base_url = account.base_url
                gitlab_record.verify_tls = account.verify_tls
                gitlab_record.ca_cert_pem = account.ca_cert_pem
                gitlab_record.enabled = account.enabled
                gitlab_record.created_at = account.created_at
                gitlab_record.updated_at = account.updated_at
                if encrypted_credential is not None:
                    gitlab_record.encrypted_credential = encrypted_credential
        return account

    def delete(self, account_id: str, *, provider: Provider) -> None:
        model = GitHubAccountRecord if provider is Provider.GITHUB else GitLabAccountRecord
        with self.sessions.begin() as session:
            record = session.get(model, account_id)
            if record is not None:
                session.delete(record)

    def set_credential(
        self,
        account_id: str,
        encrypted_value: str,
        *,
        provider: Provider,
    ) -> None:
        with self.sessions.begin() as session:
            if provider is Provider.GITHUB:
                github_record = session.get(GitHubAccountRecord, account_id)
                if github_record is None:
                    raise KeyError(f"account not found: {account_id}")
                github_record.encrypted_credential = encrypted_value
                return

            gitlab_record = session.get(GitLabAccountRecord, account_id)
            if gitlab_record is None:
                raise KeyError(f"account not found: {account_id}")
            gitlab_record.encrypted_credential = encrypted_value

    def credential(self, account_id: str, *, provider: Provider) -> str:
        with self.sessions() as session:
            if provider is Provider.GITHUB:
                github_record = session.get(GitHubAccountRecord, account_id)
                if github_record is None or not github_record.encrypted_credential:
                    raise KeyError(f"credential not configured for account: {account_id}")
                return github_record.encrypted_credential

            gitlab_record = session.get(GitLabAccountRecord, account_id)
            if gitlab_record is None or not gitlab_record.encrypted_credential:
                raise KeyError(f"credential not configured for account: {account_id}")
            return gitlab_record.encrypted_credential


class SqlAlchemyInvocationRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    @staticmethod
    def _config(session: Session) -> ManagementConfigRecord:
        config = session.get(ManagementConfigRecord, 1)
        if config is None:
            config = ManagementConfigRecord(id=1)
            session.add(config)
            session.flush()
        return config

    @staticmethod
    def _cleanup_in_session(session: Session, config: ManagementConfigRecord) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=max(config.logging_retention_days, 1))
        removed_result = cast(
            CursorResult[object],
            session.execute(
                delete(InvocationRecord).where(InvocationRecord.occurred_at < cutoff)
            ),
        )
        removed = removed_result.rowcount or 0
        count = session.scalar(select(func.count()).select_from(InvocationRecord)) or 0
        overflow = count - max(config.logging_max_records, 100)
        if overflow > 0:
            stale_ids = (
                select(InvocationRecord.id)
                .order_by(InvocationRecord.occurred_at.asc())
                .limit(overflow)
            )
            overflow_result = cast(
                CursorResult[object],
                session.execute(
                    delete(InvocationRecord).where(InvocationRecord.id.in_(stale_ids))
                ),
            )
            removed += overflow_result.rowcount or 0
        return int(removed)

    def append(self, invocation: Invocation) -> None:
        with self.sessions.begin() as session:
            config = self._config(session)
            if not config.logging_enabled:
                return
            payloads = config.logging_capture_payloads
            session.add(
                InvocationRecord(
                    id=invocation.id,
                    request_id=invocation.request_id,
                    module=invocation.module,
                    tool=invocation.tool,
                    account_id=invocation.account_id,
                    provider=invocation.provider,
                    status=invocation.status,
                    duration_ms=invocation.duration_ms,
                    error_type=invocation.error_type,
                    arguments_json=invocation.arguments_json if payloads else "",
                    result_json=invocation.result_json if payloads else "",
                    error_message=invocation.error_message if payloads else "",
                    occurred_at=invocation.occurred_at,
                )
            )
            self._cleanup_in_session(session, config)

    def recent(self, *, limit: int = 100) -> Sequence[Invocation]:
        size = max(1, min(limit, 1000))
        with self.sessions() as session:
            rows = session.scalars(
                select(InvocationRecord).order_by(InvocationRecord.occurred_at.desc()).limit(size)
            ).all()
            return [
                Invocation(
                    id=row.id,
                    request_id=row.request_id,
                    module=row.module,
                    tool=row.tool,
                    account_id=row.account_id,
                    provider=row.provider,
                    status=cast(Literal["success", "error"], row.status),
                    duration_ms=row.duration_ms,
                    error_type=row.error_type,
                    arguments_json=row.arguments_json,
                    result_json=row.result_json,
                    error_message=row.error_message,
                    occurred_at=row.occurred_at,
                )
                for row in rows
            ]

    def clear(self) -> int:
        with self.sessions.begin() as session:
            count = session.scalar(select(func.count()).select_from(InvocationRecord)) or 0
            session.execute(delete(InvocationRecord))
            return int(count)

    def cleanup(self) -> int:
        with self.sessions.begin() as session:
            return self._cleanup_in_session(session, self._config(session))


class SqlAlchemyManagementConfigRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    @staticmethod
    def _domain(record: ManagementConfigRecord) -> ManagementConfig:
        return ManagementConfig(
            logging_enabled=record.logging_enabled,
            logging_capture_payloads=record.logging_capture_payloads,
            logging_retention_days=record.logging_retention_days,
            logging_max_records=record.logging_max_records,
            maintenance_interval_minutes=record.maintenance_interval_minutes,
        )

    def get(self) -> ManagementConfig:
        with self.sessions.begin() as session:
            record = session.get(ManagementConfigRecord, 1)
            if record is None:
                record = ManagementConfigRecord(id=1)
                session.add(record)
                session.flush()
            return self._domain(record)

    def save(self, config: ManagementConfig) -> ManagementConfig:
        with self.sessions.begin() as session:
            record = session.get(ManagementConfigRecord, 1)
            if record is None:
                record = ManagementConfigRecord(id=1)
                session.add(record)
            for name, value in config.model_dump().items():
                setattr(record, name, value)
        return config
