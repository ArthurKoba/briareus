from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any, Literal, ParamSpec, TypeVar, cast

from opentelemetry import trace
from opentelemetry.trace import SpanKind
from sqlalchemy import delete, func, or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from common.runtime_policy_contracts import McpRuntimePolicy, TerminalRuntimePolicy
from management.domain.accounts import Account, AuthType, Provider
from management.domain.configuration import ManagementConfig
from management.domain.oauth_sessions import OAuthSession
from management.domain.snapshots import CachedSnapshot
from management.domain.telemetry import Invocation

from .database import (
    CachedSnapshotRecord,
    CoolifyAccountRecord,
    GitHubAccountRecord,
    GitLabAccountRecord,
    InvocationRecord,
    ManagementConfigRecord,
    McpRuntimeSettingsRecord,
    OAuthSessionRecord,
    RuntimeSettingsRecord,
    SigNozAccountRecord,
)

_P = ParamSpec("_P")
_R = TypeVar("_R")
_DB_TRACER = trace.get_tracer("mcp-bridge.management-db")


def _db_span(operation: str) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    def decorate(function: Callable[_P, _R]) -> Callable[_P, _R]:
        @wraps(function)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            with _DB_TRACER.start_as_current_span(
                f"management.db.{operation}",
                kind=SpanKind.INTERNAL,
                attributes={
                    "db.namespace": "management",
                    "db.operation.name": operation,
                },
            ):
                return function(*args, **kwargs)

        return wrapped

    return decorate


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
            verify_tls=record.verify_tls,
            ca_cert_pem=record.ca_cert_pem,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _signoz_domain(record: SigNozAccountRecord) -> Account:
        return Account(
            id=record.id,
            alias=record.alias,
            provider=Provider.SIGNOZ,
            auth_type=AuthType(record.auth_type),
            base_url=record.base_url,
            verify_tls=record.verify_tls,
            ca_cert_pem=record.ca_cert_pem,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _coolify_domain(record: CoolifyAccountRecord) -> Account:
        return Account(
            id=record.id,
            alias=record.alias,
            provider=Provider.COOLIFY,
            auth_type=AuthType(record.auth_type),
            base_url=record.base_url,
            verify_tls=record.verify_tls,
            ca_cert_pem=record.ca_cert_pem,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @_db_span("accounts.list")
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
                    self._github_domain(row) for row in session.scalars(github_stmt).all()
                )
            if provider in {None, Provider.GITLAB}:
                gitlab_stmt = select(GitLabAccountRecord)
                if enabled_only:
                    gitlab_stmt = gitlab_stmt.where(GitLabAccountRecord.enabled.is_(True))
                accounts.extend(
                    self._gitlab_domain(row) for row in session.scalars(gitlab_stmt).all()
                )
            if provider in {None, Provider.SIGNOZ}:
                signoz_stmt = select(SigNozAccountRecord)
                if enabled_only:
                    signoz_stmt = signoz_stmt.where(SigNozAccountRecord.enabled.is_(True))
                accounts.extend(
                    self._signoz_domain(row) for row in session.scalars(signoz_stmt).all()
                )
            if provider in {None, Provider.COOLIFY}:
                coolify_stmt = select(CoolifyAccountRecord)
                if enabled_only:
                    coolify_stmt = coolify_stmt.where(CoolifyAccountRecord.enabled.is_(True))
                accounts.extend(
                    self._coolify_domain(row) for row in session.scalars(coolify_stmt).all()
                )
        return sorted(accounts, key=lambda item: (item.provider.value, item.alias))

    @_db_span("accounts.get")
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
            stmt: Any
            record: Any
            if provider is Provider.GITHUB:
                stmt = select(GitHubAccountRecord).where(
                    or_(
                        GitHubAccountRecord.id == value,
                        GitHubAccountRecord.alias == value.casefold(),
                    )
                )
                if enabled_only:
                    stmt = stmt.where(GitHubAccountRecord.enabled.is_(True))
                record = session.scalar(stmt)
                if record is None:
                    raise KeyError(f"GitHub account not found: {selector}")
                return self._github_domain(record)
            if provider is Provider.GITLAB:
                stmt = select(GitLabAccountRecord).where(
                    or_(
                        GitLabAccountRecord.id == value,
                        GitLabAccountRecord.alias == value.casefold(),
                    )
                )
                if enabled_only:
                    stmt = stmt.where(GitLabAccountRecord.enabled.is_(True))
                record = session.scalar(stmt)
                if record is None:
                    raise KeyError(f"GitLab account not found: {selector}")
                return self._gitlab_domain(record)
            if provider is Provider.SIGNOZ:
                stmt = select(SigNozAccountRecord).where(
                    or_(
                        SigNozAccountRecord.id == value,
                        SigNozAccountRecord.alias == value.casefold(),
                    )
                )
                if enabled_only:
                    stmt = stmt.where(SigNozAccountRecord.enabled.is_(True))
                record = session.scalar(stmt)
                if record is None:
                    raise KeyError(f"SigNoz account not found: {selector}")
                return self._signoz_domain(record)
            stmt = select(CoolifyAccountRecord).where(
                or_(
                    CoolifyAccountRecord.id == value, CoolifyAccountRecord.alias == value.casefold()
                )
            )
            if enabled_only:
                stmt = stmt.where(CoolifyAccountRecord.enabled.is_(True))
            record = session.scalar(stmt)
            if record is None:
                raise KeyError(f"Coolify account not found: {selector}")
            return self._coolify_domain(record)

    @_db_span("accounts.save")
    def save(self, account: Account, *, encrypted_credential: str | None = None) -> Account:
        with self.sessions.begin() as session:
            record: Any
            if account.provider is Provider.GITHUB:
                record = session.get(GitHubAccountRecord, account.id) or GitHubAccountRecord(
                    id=account.id
                )
                session.add(record)
                record.app_id = account.external_id
            elif account.provider is Provider.GITLAB:
                record = session.get(GitLabAccountRecord, account.id) or GitLabAccountRecord(
                    id=account.id
                )
                session.add(record)
                record.base_url = account.base_url
                record.verify_tls = account.verify_tls
                record.ca_cert_pem = account.ca_cert_pem
            elif account.provider is Provider.SIGNOZ:
                record = session.get(SigNozAccountRecord, account.id) or SigNozAccountRecord(
                    id=account.id
                )
                session.add(record)
                record.base_url = account.base_url
                record.verify_tls = account.verify_tls
                record.ca_cert_pem = account.ca_cert_pem
            else:
                record = session.get(CoolifyAccountRecord, account.id) or CoolifyAccountRecord(
                    id=account.id
                )
                session.add(record)
                record.base_url = account.base_url
                record.verify_tls = account.verify_tls
                record.ca_cert_pem = account.ca_cert_pem
            record.alias = account.alias
            record.auth_type = account.auth_type.value
            record.enabled = account.enabled
            record.created_at = account.created_at
            record.updated_at = account.updated_at
            if encrypted_credential is not None:
                record.encrypted_credential = encrypted_credential
        return account

    @_db_span("accounts.delete")
    def delete(self, account_id: str, *, provider: Provider) -> None:
        with self.sessions.begin() as session:
            record: Any
            if provider is Provider.GITHUB:
                record = session.get(GitHubAccountRecord, account_id)
            elif provider is Provider.GITLAB:
                record = session.get(GitLabAccountRecord, account_id)
            elif provider is Provider.SIGNOZ:
                record = session.get(SigNozAccountRecord, account_id)
            else:
                record = session.get(CoolifyAccountRecord, account_id)
            if record is not None:
                session.delete(record)

    @_db_span("accounts.set_credential")
    def set_credential(
        self,
        account_id: str,
        encrypted_value: str,
        *,
        provider: Provider,
    ) -> None:
        with self.sessions.begin() as session:
            record: Any
            if provider is Provider.GITHUB:
                record = session.get(GitHubAccountRecord, account_id)
            elif provider is Provider.GITLAB:
                record = session.get(GitLabAccountRecord, account_id)
            elif provider is Provider.SIGNOZ:
                record = session.get(SigNozAccountRecord, account_id)
            else:
                record = session.get(CoolifyAccountRecord, account_id)
            if record is None:
                raise KeyError(f"account not found: {account_id}")
            record.encrypted_credential = encrypted_value

    @_db_span("accounts.credential")
    def credential(self, account_id: str, *, provider: Provider) -> str:
        with self.sessions() as session:
            record: Any
            if provider is Provider.GITHUB:
                record = session.get(GitHubAccountRecord, account_id)
            elif provider is Provider.GITLAB:
                record = session.get(GitLabAccountRecord, account_id)
            elif provider is Provider.SIGNOZ:
                record = session.get(SigNozAccountRecord, account_id)
            else:
                record = session.get(CoolifyAccountRecord, account_id)
            if record is None or not record.encrypted_credential:
                raise KeyError(f"credential not configured for account: {account_id}")
            return str(record.encrypted_credential)


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
            session.execute(delete(InvocationRecord).where(InvocationRecord.occurred_at < cutoff)),
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
                session.execute(delete(InvocationRecord).where(InvocationRecord.id.in_(stale_ids))),
            )
            removed += overflow_result.rowcount or 0
        return int(removed)

    @staticmethod
    def _record(invocation: Invocation, *, capture_payloads: bool) -> InvocationRecord:
        return InvocationRecord(
            id=invocation.id,
            request_id=invocation.request_id,
            module=invocation.module,
            tool=invocation.tool,
            account_id=invocation.account_id,
            provider=invocation.provider,
            status=invocation.status,
            duration_ms=invocation.duration_ms,
            error_type=invocation.error_type,
            arguments_json=invocation.arguments_json if capture_payloads else "",
            result_json=invocation.result_json if capture_payloads else "",
            error_message=invocation.error_message if capture_payloads else "",
            occurred_at=invocation.occurred_at,
        )

    def append(self, invocation: Invocation, *, capture_payloads: bool = True) -> None:
        self.append_many([invocation], capture_payloads=capture_payloads)

    @_db_span("audit.append_many")
    def append_many(
        self,
        invocations: Sequence[Invocation],
        *,
        capture_payloads: bool = True,
    ) -> None:
        if not invocations:
            return
        trace.get_current_span().set_attribute("db.batch.size", len(invocations))
        with self.sessions.begin() as session:
            session.add_all(
                [
                    self._record(invocation, capture_payloads=capture_payloads)
                    for invocation in invocations
                ]
            )

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

    @_db_span("audit.cleanup")
    def cleanup(self) -> int:
        with self.sessions.begin() as session:
            return self._cleanup_in_session(session, self._config(session))


class SqlAlchemyOAuthSessionRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    @staticmethod
    def _domain(record: OAuthSessionRecord) -> OAuthSession:
        try:
            scopes = json.loads(record.scopes_json)
        except json.JSONDecodeError:
            scopes = []
        return OAuthSession(
            id=record.id,
            client_id=record.client_id,
            client_name=record.client_name,
            resource=record.resource,
            login=record.login,
            subject=record.subject,
            scopes=[str(item) for item in scopes] if isinstance(scopes, list) else [],
            status=record.status,
            last_event=record.last_event,
            access_jti=record.access_jti,
            refresh_jti=record.refresh_jti,
            previous_refresh_jti=record.previous_refresh_jti,
            access_expires_at=record.access_expires_at,
            refresh_expires_at=record.refresh_expires_at,
            last_used_at=record.last_used_at,
            last_refresh_at=record.last_refresh_at,
            revoked_at=record.revoked_at,
            error_type=record.error_type,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _resolve_record(
        self,
        session: Session,
        *,
        session_id: str,
        refresh_jti: str,
        access_jti: str,
        client_id: str,
        resource: str,
        login: str,
    ) -> OAuthSessionRecord | None:
        if session_id:
            record = session.get(OAuthSessionRecord, session_id)
            if record is not None:
                return record
        if refresh_jti or access_jti:
            criteria = []
            if refresh_jti:
                criteria.extend(
                    [
                        OAuthSessionRecord.refresh_jti == refresh_jti,
                        OAuthSessionRecord.previous_refresh_jti == refresh_jti,
                    ]
                )
            if access_jti:
                criteria.append(OAuthSessionRecord.access_jti == access_jti)
            record = session.scalar(select(OAuthSessionRecord).where(or_(*criteria)))
            if record is not None:
                return record
        if client_id and resource:
            stmt = select(OAuthSessionRecord).where(
                OAuthSessionRecord.client_id == client_id,
                OAuthSessionRecord.resource == resource,
            )
            if login:
                stmt = stmt.where(OAuthSessionRecord.login == login)
            return session.scalar(stmt.order_by(OAuthSessionRecord.updated_at.desc()))
        return None

    def apply_event(self, event: object) -> OAuthSession:
        from common.oauth_session_contracts import OAuthSessionEvent

        value = OAuthSessionEvent.model_validate(event)
        with self.sessions.begin() as session:
            record = self._resolve_record(
                session,
                session_id=value.session_id,
                refresh_jti=value.refresh_jti,
                access_jti=value.access_jti,
                client_id=value.client_id,
                resource=value.resource,
                login=value.login,
            )
            if record is None:
                identity = "\0".join((value.client_id, value.resource, value.login))
                identity_id = (
                    "observed-" + hashlib.sha256(identity.encode()).hexdigest()[:32]
                    if value.client_id and value.resource
                    else ""
                )
                identifier = (
                    value.session_id
                    or identity_id
                    or f"orphan-{value.refresh_jti or value.access_jti}"
                )
                if not identifier or identifier == "orphan-":
                    raise ValueError("oauth session event has no stable identifier")
                record = OAuthSessionRecord(
                    id=identifier[:128],
                    client_id=value.client_id,
                    created_at=value.occurred_at,
                )
                session.add(record)

            if value.client_id:
                record.client_id = value.client_id
            if value.client_name:
                record.client_name = value.client_name
            if value.resource:
                record.resource = value.resource
            if value.login:
                record.login = value.login
            if value.subject:
                record.subject = value.subject
            if value.scopes:
                record.scopes_json = json.dumps(value.scopes, ensure_ascii=False)
            if value.access_jti:
                record.access_jti = value.access_jti
            if value.refresh_jti and value.refresh_jti != record.refresh_jti:
                record.previous_refresh_jti = record.refresh_jti
                record.refresh_jti = value.refresh_jti
            if value.access_expires_at is not None:
                record.access_expires_at = value.access_expires_at
            if value.refresh_expires_at is not None:
                record.refresh_expires_at = value.refresh_expires_at

            record.status = value.status
            record.last_event = value.event
            record.updated_at = value.occurred_at
            successful_refresh = (
                value.event.startswith("refresh_success")
                or value.event.startswith("refresh_replay")
            )
            if value.event in {"authorized", "access_used"} or successful_refresh:
                record.last_used_at = value.occurred_at
            if successful_refresh:
                record.last_refresh_at = value.occurred_at
            if value.event == "revoked":
                record.revoked_at = value.occurred_at
            if value.error_type or value.error_message:
                record.error_type = value.error_type
                record.error_message = value.error_message
            elif value.status == "active":
                record.error_type = ""
                record.error_message = ""

            session.flush()
            return self._domain(record)

    def recent(self, *, limit: int = 200) -> Sequence[OAuthSession]:
        size = max(1, min(limit, 1000))
        with self.sessions() as session:
            rows = session.scalars(
                select(OAuthSessionRecord)
                .order_by(OAuthSessionRecord.updated_at.desc())
                .limit(size)
            ).all()
            return [self._domain(row) for row in rows]


class SqlAlchemySnapshotRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    @staticmethod
    def _decode_object(value: str) -> dict[str, object]:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @classmethod
    def _domain(cls, record: CachedSnapshotRecord) -> CachedSnapshot:
        from common.models import json_object

        return CachedSnapshot(
            key=record.key,
            category=record.category,
            parameters=json_object(
                cls._decode_object(record.parameters_json),
                context="cached snapshot parameters",
            ),
            payload=json_object(
                cls._decode_object(record.payload_json),
                context="cached snapshot payload",
            ),
            refresh_after_seconds=record.refresh_after_seconds,
            status=record.status,
            updated_at=record.updated_at,
            attempted_at=record.attempted_at,
            error_type=record.error_type,
            error_message=record.error_message,
            created_at=record.created_at,
        )

    @_db_span("snapshots.ensure")
    def ensure(
        self,
        key: str,
        *,
        category: str,
        parameters: dict[str, object] | None = None,
        refresh_after_seconds: int,
    ) -> CachedSnapshot:
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            record = session.get(CachedSnapshotRecord, key)
            if record is None:
                record = CachedSnapshotRecord(
                    key=key,
                    category=category,
                    parameters_json=json.dumps(parameters or {}, ensure_ascii=False),
                    refresh_after_seconds=refresh_after_seconds,
                    created_at=now,
                )
                session.add(record)
            else:
                record.category = category
                record.parameters_json = json.dumps(parameters or {}, ensure_ascii=False)
                record.refresh_after_seconds = refresh_after_seconds
            session.flush()
            return self._domain(record)

    @_db_span("snapshots.get")
    def get(self, key: str) -> CachedSnapshot | None:
        with self.sessions() as session:
            record = session.get(CachedSnapshotRecord, key)
            return self._domain(record) if record is not None else None

    @_db_span("snapshots.list_category")
    def list_category(self, category: str, *, limit: int = 1000) -> Sequence[CachedSnapshot]:
        size = max(1, min(limit, 5000))
        with self.sessions() as session:
            rows = session.scalars(
                select(CachedSnapshotRecord)
                .where(CachedSnapshotRecord.category == category)
                .order_by(CachedSnapshotRecord.created_at.asc())
                .limit(size)
            ).all()
            return [self._domain(row) for row in rows]

    @_db_span("snapshots.mark_attempt")
    def mark_attempt(self, key: str, *, status: str = "refreshing") -> None:
        with self.sessions.begin() as session:
            record = session.get(CachedSnapshotRecord, key)
            if record is None:
                raise KeyError(key)
            record.attempted_at = datetime.now(UTC)
            record.status = status

    @_db_span("snapshots.store_success")
    def store_success(self, key: str, payload: dict[str, object]) -> CachedSnapshot:
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            record = session.get(CachedSnapshotRecord, key)
            if record is None:
                raise KeyError(key)
            record.payload_json = json.dumps(payload, ensure_ascii=False)
            record.status = "ready"
            record.updated_at = now
            record.attempted_at = now
            record.error_type = ""
            record.error_message = ""
            session.flush()
            return self._domain(record)

    @_db_span("snapshots.store_error")
    def store_error(self, key: str, exc: Exception) -> CachedSnapshot:
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            record = session.get(CachedSnapshotRecord, key)
            if record is None:
                raise KeyError(key)
            record.status = "error"
            record.attempted_at = now
            record.error_type = type(exc).__name__
            record.error_message = str(exc)[:4096]
            session.flush()
            return self._domain(record)


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

    @_db_span("config.get")
    def get(self) -> ManagementConfig:
        with self.sessions.begin() as session:
            record = session.get(ManagementConfigRecord, 1)
            if record is None:
                record = ManagementConfigRecord(id=1)
                session.add(record)
                session.flush()
            return self._domain(record)

    @_db_span("config.save")
    def save(self, config: ManagementConfig) -> ManagementConfig:
        with self.sessions.begin() as session:
            record = session.get(ManagementConfigRecord, 1)
            if record is None:
                record = ManagementConfigRecord(id=1)
                session.add(record)
            for name, value in config.model_dump().items():
                setattr(record, name, value)
        return config


class SqlAlchemyRuntimeSettingsRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    @staticmethod
    def _domain(record: RuntimeSettingsRecord) -> TerminalRuntimePolicy:
        return TerminalRuntimePolicy(
            max_exec_timeout_seconds=record.terminal_max_exec_timeout_seconds,
            max_job_runtime_seconds=record.terminal_max_job_runtime_seconds,
        )

    @_db_span("runtime.terminal.get")
    def get_terminal_policy(self) -> TerminalRuntimePolicy:
        with self.sessions.begin() as session:
            record = session.get(RuntimeSettingsRecord, 1)
            if record is None:
                record = RuntimeSettingsRecord(id=1)
                session.add(record)
                session.flush()
            elif (
                record.terminal_max_exec_timeout_seconds == 300
                and record.terminal_max_job_runtime_seconds == 3600
            ):
                record.terminal_max_exec_timeout_seconds = 21_600
                record.terminal_max_job_runtime_seconds = 43_200
                session.flush()
            return self._domain(record)

    @_db_span("runtime.terminal.save")
    def save_terminal_policy(
        self,
        policy: TerminalRuntimePolicy,
    ) -> TerminalRuntimePolicy:
        with self.sessions.begin() as session:
            record = session.get(RuntimeSettingsRecord, 1)
            if record is None:
                record = RuntimeSettingsRecord(id=1)
                session.add(record)
            record.terminal_max_exec_timeout_seconds = policy.max_exec_timeout_seconds
            record.terminal_max_job_runtime_seconds = policy.max_job_runtime_seconds
        return policy

    @_db_span("runtime.mcp.get")
    def get_mcp_policy(self) -> McpRuntimePolicy:
        with self.sessions.begin() as session:
            record = session.get(McpRuntimeSettingsRecord, 1)
            if record is None:
                record = McpRuntimeSettingsRecord(id=1)
                session.add(record)
                session.flush()
            return McpRuntimePolicy(call_timeout_seconds=record.call_timeout_seconds)

    @_db_span("runtime.mcp.save")
    def save_mcp_policy(self, policy: McpRuntimePolicy) -> McpRuntimePolicy:
        with self.sessions.begin() as session:
            record = session.get(McpRuntimeSettingsRecord, 1)
            if record is None:
                record = McpRuntimeSettingsRecord(id=1)
                session.add(record)
            record.call_timeout_seconds = policy.call_timeout_seconds
        return policy
