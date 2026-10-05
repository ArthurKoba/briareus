from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Coroutine, Sequence
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any, Literal, ParamSpec, TypeVar, cast

from domain.accounts import Account, AccountConflictError, AuthType, Provider
from domain.configuration import AdminConfig
from domain.oauth_sessions import OAuthSession
from domain.snapshots import CachedSnapshot
from domain.telemetry import Invocation, InvocationPage, InvocationQuery
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.runtime_policy_contracts import (
    GitHubRuntimePolicy,
    GitLabRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)

from .database import (
    AdminConfigRecord,
    CachedSnapshotRecord,
    CoolifyAccountRecord,
    GitHubAccountRecord,
    GitHubRuntimeSettingsRecord,
    GitLabAccountRecord,
    GitLabRuntimeSettingsRecord,
    InvocationRecord,
    McpRuntimeSettingsRecord,
    OAuthSessionRecord,
    RuntimeSettingsRecord,
    SigNozAccountRecord,
)

_P = ParamSpec("_P")
_R = TypeVar("_R")
_DB_TRACER = trace.get_tracer("mcp-bridge.admin-api-db")


def _db_span(
    operation: str,
) -> Callable[[Callable[_P, Coroutine[Any, Any, _R]]], Callable[_P, Coroutine[Any, Any, _R]]]:
    def decorate(
        function: Callable[_P, Coroutine[Any, Any, _R]],
    ) -> Callable[_P, Coroutine[Any, Any, _R]]:
        @wraps(function)
        async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            with _DB_TRACER.start_as_current_span(
                f"admin-api.db.{operation}",
                kind=SpanKind.INTERNAL,
                attributes={
                    "db.namespace": "admin-api",
                    "db.operation.name": operation,
                },
            ):
                return await function(*args, **kwargs)

        return wrapped

    return decorate


class SqlAlchemyAccountRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
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
    async def list(
        self,
        *,
        provider: Provider | None = None,
        enabled_only: bool = True,
    ) -> Sequence[Account]:
        accounts: list[Account] = []
        async with self.sessions() as session:
            if provider in {None, Provider.GITHUB}:
                github_stmt = select(GitHubAccountRecord)
                if enabled_only:
                    github_stmt = github_stmt.where(GitHubAccountRecord.enabled.is_(True))
                accounts.extend(
                    self._github_domain(row) for row in (await session.scalars(github_stmt)).all()
                )
            if provider in {None, Provider.GITLAB}:
                gitlab_stmt = select(GitLabAccountRecord)
                if enabled_only:
                    gitlab_stmt = gitlab_stmt.where(GitLabAccountRecord.enabled.is_(True))
                accounts.extend(
                    self._gitlab_domain(row) for row in (await session.scalars(gitlab_stmt)).all()
                )
            if provider in {None, Provider.SIGNOZ}:
                signoz_stmt = select(SigNozAccountRecord)
                if enabled_only:
                    signoz_stmt = signoz_stmt.where(SigNozAccountRecord.enabled.is_(True))
                accounts.extend(
                    self._signoz_domain(row) for row in (await session.scalars(signoz_stmt)).all()
                )
            if provider in {None, Provider.COOLIFY}:
                coolify_stmt = select(CoolifyAccountRecord)
                if enabled_only:
                    coolify_stmt = coolify_stmt.where(CoolifyAccountRecord.enabled.is_(True))
                accounts.extend(
                    self._coolify_domain(row) for row in (await session.scalars(coolify_stmt)).all()
                )
        return sorted(accounts, key=lambda item: (item.provider.value, item.alias))

    @_db_span("accounts.get")
    async def get(
        self,
        selector: str,
        *,
        provider: Provider,
        enabled_only: bool = True,
    ) -> Account:
        value = selector.strip()
        if not value:
            raise KeyError("account selector is required")
        async with self.sessions() as session:
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
                record = await session.scalar(stmt)
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
                record = await session.scalar(stmt)
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
                record = await session.scalar(stmt)
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
            record = await session.scalar(stmt)
            if record is None:
                raise KeyError(f"Coolify account not found: {selector}")
            return self._coolify_domain(record)

    @_db_span("accounts.save")
    async def save(
        self,
        account: Account,
        *,
        encrypted_credential: str | None = None,
        expected_updated_at: datetime | None = None,
    ) -> Account:
        if expected_updated_at is not None:
            model: (
                type[GitHubAccountRecord]
                | type[GitLabAccountRecord]
                | type[SigNozAccountRecord]
                | type[CoolifyAccountRecord]
            )
            values: dict[str, object] = {
                "alias": account.alias,
                "auth_type": account.auth_type.value,
                "enabled": account.enabled,
                "updated_at": account.updated_at,
            }
            if account.provider is Provider.GITHUB:
                model = GitHubAccountRecord
                values["app_id"] = account.external_id
            elif account.provider is Provider.GITLAB:
                model = GitLabAccountRecord
                values.update(
                    base_url=account.base_url,
                    verify_tls=account.verify_tls,
                    ca_cert_pem=account.ca_cert_pem,
                )
            elif account.provider is Provider.SIGNOZ:
                model = SigNozAccountRecord
                values.update(
                    base_url=account.base_url,
                    verify_tls=account.verify_tls,
                    ca_cert_pem=account.ca_cert_pem,
                )
            else:
                model = CoolifyAccountRecord
                values.update(
                    base_url=account.base_url,
                    verify_tls=account.verify_tls,
                    ca_cert_pem=account.ca_cert_pem,
                )
            if encrypted_credential is not None:
                values["encrypted_credential"] = encrypted_credential
            async with self.sessions.begin() as session:
                result = cast(
                    CursorResult[object],
                    await session.execute(
                        update(model)
                        .where(model.id == account.id, model.updated_at == expected_updated_at)
                        .values(**values)
                    ),
                )
                if result.rowcount != 1:
                    raise AccountConflictError("account changed since it was loaded")
            return account

        async with self.sessions.begin() as session:
            record: Any
            if account.provider is Provider.GITHUB:
                record = await session.get(GitHubAccountRecord, account.id) or GitHubAccountRecord(
                    id=account.id
                )
                session.add(record)
                record.app_id = account.external_id
            elif account.provider is Provider.GITLAB:
                record = await session.get(GitLabAccountRecord, account.id) or GitLabAccountRecord(
                    id=account.id
                )
                session.add(record)
                record.base_url = account.base_url
                record.verify_tls = account.verify_tls
                record.ca_cert_pem = account.ca_cert_pem
            elif account.provider is Provider.SIGNOZ:
                record = await session.get(SigNozAccountRecord, account.id) or SigNozAccountRecord(
                    id=account.id
                )
                session.add(record)
                record.base_url = account.base_url
                record.verify_tls = account.verify_tls
                record.ca_cert_pem = account.ca_cert_pem
            else:
                record = await session.get(
                    CoolifyAccountRecord, account.id
                ) or CoolifyAccountRecord(id=account.id)
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
    async def delete(self, account_id: str, *, provider: Provider) -> None:
        async with self.sessions.begin() as session:
            record: Any
            if provider is Provider.GITHUB:
                record = await session.get(GitHubAccountRecord, account_id)
            elif provider is Provider.GITLAB:
                record = await session.get(GitLabAccountRecord, account_id)
            elif provider is Provider.SIGNOZ:
                record = await session.get(SigNozAccountRecord, account_id)
            else:
                record = await session.get(CoolifyAccountRecord, account_id)
            if record is not None:
                await session.delete(record)

    @_db_span("accounts.set_credential")
    async def set_credential(
        self,
        account_id: str,
        encrypted_value: str,
        *,
        provider: Provider,
    ) -> None:
        async with self.sessions.begin() as session:
            record: Any
            if provider is Provider.GITHUB:
                record = await session.get(GitHubAccountRecord, account_id)
            elif provider is Provider.GITLAB:
                record = await session.get(GitLabAccountRecord, account_id)
            elif provider is Provider.SIGNOZ:
                record = await session.get(SigNozAccountRecord, account_id)
            else:
                record = await session.get(CoolifyAccountRecord, account_id)
            if record is None:
                raise KeyError(f"account not found: {account_id}")
            record.encrypted_credential = encrypted_value
            record.updated_at = datetime.now(UTC)

    @_db_span("accounts.credential")
    async def credential(self, account_id: str, *, provider: Provider) -> str:
        async with self.sessions() as session:
            record: Any
            if provider is Provider.GITHUB:
                record = await session.get(GitHubAccountRecord, account_id)
            elif provider is Provider.GITLAB:
                record = await session.get(GitLabAccountRecord, account_id)
            elif provider is Provider.SIGNOZ:
                record = await session.get(SigNozAccountRecord, account_id)
            else:
                record = await session.get(CoolifyAccountRecord, account_id)
            if record is None or not record.encrypted_credential:
                raise KeyError(f"credential not configured for account: {account_id}")
            return str(record.encrypted_credential)


class SqlAlchemyInvocationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @staticmethod
    async def _config(session: AsyncSession) -> AdminConfigRecord:
        config = await session.get(AdminConfigRecord, 1)
        if config is None:
            config = AdminConfigRecord(id=1)
            session.add(config)
            await session.flush()
        return config

    @staticmethod
    async def _cleanup_in_session(session: AsyncSession, config: AdminConfigRecord) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=max(config.logging_retention_days, 1))
        removed_result = cast(
            CursorResult[object],
            await session.execute(
                delete(InvocationRecord).where(InvocationRecord.occurred_at < cutoff)
            ),
        )
        removed = removed_result.rowcount or 0
        count = await session.scalar(select(func.count()).select_from(InvocationRecord)) or 0
        overflow = count - max(config.logging_max_records, 100)
        if overflow > 0:
            stale_ids = (
                select(InvocationRecord.id)
                .order_by(InvocationRecord.occurred_at.asc())
                .limit(overflow)
            )
            overflow_result = cast(
                CursorResult[object],
                await session.execute(
                    delete(InvocationRecord).where(InvocationRecord.id.in_(stale_ids))
                ),
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

    async def append(self, invocation: Invocation, *, capture_payloads: bool = True) -> None:
        await self.append_many([invocation], capture_payloads=capture_payloads)

    @_db_span("audit.append_many")
    async def append_many(
        self,
        invocations: Sequence[Invocation],
        *,
        capture_payloads: bool = True,
    ) -> None:
        if not invocations:
            return
        trace.get_current_span().set_attribute("db.batch.size", len(invocations))
        async with self.sessions.begin() as session:
            session.add_all(
                [
                    self._record(invocation, capture_payloads=capture_payloads)
                    for invocation in invocations
                ]
            )

    @staticmethod
    def _invocation(row: InvocationRecord) -> Invocation:
        return Invocation(
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

    async def query(self, query: InvocationQuery) -> InvocationPage:
        filters: list[Any] = []
        if query.module:
            filters.append(InvocationRecord.module == query.module)
        if query.tool:
            filters.append(InvocationRecord.tool == query.tool)
        if query.provider:
            filters.append(InvocationRecord.provider == query.provider)
        if query.account_id:
            filters.append(InvocationRecord.account_id == query.account_id)
        if query.status is not None:
            filters.append(InvocationRecord.status == query.status)
        if query.search:
            pattern = f"%{query.search.strip()}%"
            filters.append(
                or_(
                    InvocationRecord.module.ilike(pattern),
                    InvocationRecord.tool.ilike(pattern),
                    InvocationRecord.request_id.ilike(pattern),
                    InvocationRecord.provider.ilike(pattern),
                    InvocationRecord.account_id.ilike(pattern),
                )
            )

        async with self.sessions() as session:
            total = (
                await session.scalar(
                    select(func.count()).select_from(InvocationRecord).where(*filters)
                )
                or 0
            )
            stmt = select(InvocationRecord).where(*filters)
            if query.cursor_at is not None and query.cursor_id:
                stmt = stmt.where(
                    or_(
                        InvocationRecord.occurred_at < query.cursor_at,
                        and_(
                            InvocationRecord.occurred_at == query.cursor_at,
                            InvocationRecord.id < query.cursor_id,
                        ),
                    )
                )
            elif query.offset:
                stmt = stmt.offset(query.offset)
            rows = (
                await session.scalars(
                    stmt.order_by(
                        InvocationRecord.occurred_at.desc(), InvocationRecord.id.desc()
                    ).limit(query.limit + 1)
                )
            ).all()

        has_more = len(rows) > query.limit
        visible = rows[: query.limit]
        events = [self._invocation(row) for row in visible]
        tail = visible[-1] if visible and has_more else None
        return InvocationPage(
            events=events,
            total=int(total),
            count=len(events),
            has_more=has_more,
            next_cursor_at=tail.occurred_at if tail is not None else None,
            next_cursor_id=tail.id if tail is not None else "",
        )

    async def recent(self, *, limit: int = 100) -> Sequence[Invocation]:
        return (await self.query(InvocationQuery(limit=max(1, min(limit, 500))))).events

    async def clear(self) -> int:
        async with self.sessions.begin() as session:
            count = await session.scalar(select(func.count()).select_from(InvocationRecord)) or 0
            await session.execute(delete(InvocationRecord))
            return int(count)

    async def delete(self, invocation_id: str) -> bool:
        async with self.sessions.begin() as session:
            result = cast(
                CursorResult[object],
                await session.execute(
                    delete(InvocationRecord).where(InvocationRecord.id == invocation_id)
                ),
            )
            return bool(result.rowcount)

    async def summary(self) -> dict[str, int | float]:
        async with self.sessions() as session:
            total = await session.scalar(select(func.count()).select_from(InvocationRecord)) or 0
            errors = (
                await session.scalar(
                    select(func.count())
                    .select_from(InvocationRecord)
                    .where(InvocationRecord.status == "error")
                )
                or 0
            )
            average = await session.scalar(select(func.avg(InvocationRecord.duration_ms))) or 0.0
        return {
            "total": int(total),
            "errors": int(errors),
            "error_rate": round((float(errors) * 100.0 / float(total)), 1) if total else 0.0,
            "average_duration_ms": round(float(average), 1),
        }

    @_db_span("audit.cleanup")
    async def cleanup(self) -> int:
        async with self.sessions.begin() as session:
            return await self._cleanup_in_session(session, await self._config(session))


class SqlAlchemyOAuthSessionRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
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

    async def _resolve_record(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        refresh_jti: str,
        access_jti: str,
        client_id: str,
        resource: str,
        login: str,
    ) -> OAuthSessionRecord | None:
        if session_id:
            record = await session.get(OAuthSessionRecord, session_id)
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
            record = cast(
                OAuthSessionRecord | None,
                await session.scalar(select(OAuthSessionRecord).where(or_(*criteria))),
            )
            if record is not None:
                return record
        if client_id and resource:
            stmt = select(OAuthSessionRecord).where(
                OAuthSessionRecord.client_id == client_id,
                OAuthSessionRecord.resource == resource,
            )
            if login:
                stmt = stmt.where(OAuthSessionRecord.login == login)
            return cast(
                OAuthSessionRecord | None,
                await session.scalar(stmt.order_by(OAuthSessionRecord.updated_at.desc())),
            )
        return None

    async def apply_event(self, event: object) -> OAuthSession:
        from common.oauth_session_contracts import OAuthSessionEvent

        value = OAuthSessionEvent.model_validate(event)
        async with self.sessions.begin() as session:
            record = await self._resolve_record(
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
            successful_refresh = value.event.startswith(
                "refresh_success"
            ) or value.event.startswith("refresh_replay")
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

            await session.flush()
            return self._domain(record)

    async def recent(self, *, limit: int = 200) -> Sequence[OAuthSession]:
        size = max(1, min(limit, 1000))
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(OAuthSessionRecord)
                    .order_by(OAuthSessionRecord.updated_at.desc())
                    .limit(size)
                )
            ).all()
            return [self._domain(row) for row in rows]


class SqlAlchemySnapshotRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
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
    async def ensure(
        self,
        key: str,
        *,
        category: str,
        parameters: dict[str, object] | None = None,
        refresh_after_seconds: int,
    ) -> CachedSnapshot:
        now = datetime.now(UTC)
        async with self.sessions.begin() as session:
            record = await session.get(CachedSnapshotRecord, key)
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
            await session.flush()
            return self._domain(record)

    @_db_span("snapshots.get")
    async def get(self, key: str) -> CachedSnapshot | None:
        async with self.sessions() as session:
            record = await session.get(CachedSnapshotRecord, key)
            return self._domain(record) if record is not None else None

    @_db_span("snapshots.list_category")
    async def list_category(self, category: str, *, limit: int = 1000) -> Sequence[CachedSnapshot]:
        size = max(1, min(limit, 5000))
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(CachedSnapshotRecord)
                    .where(CachedSnapshotRecord.category == category)
                    .order_by(CachedSnapshotRecord.created_at.asc())
                    .limit(size)
                )
            ).all()
            return [self._domain(row) for row in rows]

    @_db_span("snapshots.mark_attempt")
    async def mark_attempt(self, key: str, *, status: str = "refreshing") -> None:
        async with self.sessions.begin() as session:
            record = await session.get(CachedSnapshotRecord, key)
            if record is None:
                raise KeyError(key)
            record.attempted_at = datetime.now(UTC)
            record.status = status

    @_db_span("snapshots.store_success")
    async def store_success(self, key: str, payload: dict[str, object]) -> CachedSnapshot:
        now = datetime.now(UTC)
        async with self.sessions.begin() as session:
            record = await session.get(CachedSnapshotRecord, key)
            if record is None:
                raise KeyError(key)
            record.payload_json = json.dumps(payload, ensure_ascii=False)
            record.status = "ready"
            record.updated_at = now
            record.attempted_at = now
            record.error_type = ""
            record.error_message = ""
            await session.flush()
            return self._domain(record)

    @_db_span("snapshots.store_error")
    async def store_error(self, key: str, exc: Exception) -> CachedSnapshot:
        now = datetime.now(UTC)
        async with self.sessions.begin() as session:
            record = await session.get(CachedSnapshotRecord, key)
            if record is None:
                raise KeyError(key)
            record.status = "error"
            record.attempted_at = now
            record.error_type = type(exc).__name__
            record.error_message = str(exc)[:4096]
            await session.flush()
            return self._domain(record)


class SqlAlchemyAdminConfigRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @staticmethod
    def _domain(record: AdminConfigRecord) -> AdminConfig:
        return AdminConfig(
            logging_enabled=record.logging_enabled,
            logging_capture_payloads=record.logging_capture_payloads,
            logging_retention_days=record.logging_retention_days,
            logging_max_records=record.logging_max_records,
            maintenance_interval_minutes=record.maintenance_interval_minutes,
        )

    @_db_span("config.get")
    async def get(self) -> AdminConfig:
        async with self.sessions.begin() as session:
            record = await session.get(AdminConfigRecord, 1)
            if record is None:
                record = AdminConfigRecord(id=1)
                session.add(record)
                await session.flush()
            return self._domain(record)

    @_db_span("config.save")
    async def save(self, config: AdminConfig) -> AdminConfig:
        async with self.sessions.begin() as session:
            record = await session.get(AdminConfigRecord, 1)
            if record is None:
                record = AdminConfigRecord(id=1)
                session.add(record)
            for name, value in config.model_dump().items():
                setattr(record, name, value)
        return config


class SqlAlchemyRuntimeSettingsRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @staticmethod
    def _domain(record: RuntimeSettingsRecord) -> TerminalRuntimePolicy:
        return TerminalRuntimePolicy(
            max_exec_timeout_seconds=record.terminal_max_exec_timeout_seconds,
            max_job_runtime_seconds=record.terminal_max_job_runtime_seconds,
        )

    @_db_span("runtime.terminal.get")
    async def get_terminal_policy(self) -> TerminalRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(RuntimeSettingsRecord, 1)
            if record is None:
                record = RuntimeSettingsRecord(id=1)
                session.add(record)
                await session.flush()
            elif (
                record.terminal_max_exec_timeout_seconds == 300
                and record.terminal_max_job_runtime_seconds == 3600
            ):
                record.terminal_max_exec_timeout_seconds = 21_600
                record.terminal_max_job_runtime_seconds = 43_200
                await session.flush()
            return self._domain(record)

    @_db_span("runtime.terminal.save")
    async def save_terminal_policy(
        self,
        policy: TerminalRuntimePolicy,
    ) -> TerminalRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(RuntimeSettingsRecord, 1)
            if record is None:
                record = RuntimeSettingsRecord(id=1)
                session.add(record)
            record.terminal_max_exec_timeout_seconds = policy.max_exec_timeout_seconds
            record.terminal_max_job_runtime_seconds = policy.max_job_runtime_seconds
        return policy

    @_db_span("runtime.mcp.get")
    async def get_mcp_policy(self) -> McpRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(McpRuntimeSettingsRecord, 1)
            if record is None:
                record = McpRuntimeSettingsRecord(id=1)
                session.add(record)
                await session.flush()
            return McpRuntimePolicy(call_timeout_seconds=record.call_timeout_seconds)

    @_db_span("runtime.mcp.save")
    async def save_mcp_policy(self, policy: McpRuntimePolicy) -> McpRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(McpRuntimeSettingsRecord, 1)
            if record is None:
                record = McpRuntimeSettingsRecord(id=1)
                session.add(record)
            record.call_timeout_seconds = policy.call_timeout_seconds
        return policy

    @_db_span("runtime.github.get")
    async def get_github_policy(self) -> GitHubRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(GitHubRuntimeSettingsRecord, 1)
            if record is None:
                record = GitHubRuntimeSettingsRecord(id=1)
                session.add(record)
                await session.flush()
            return GitHubRuntimePolicy(
                local_first_guidance=record.local_first_guidance,
                local_git_transport_enabled=record.local_git_transport_enabled,
                remote_source_mutations_enabled=record.remote_source_mutations_enabled,
            )

    @_db_span("runtime.github.save")
    async def save_github_policy(self, policy: GitHubRuntimePolicy) -> GitHubRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(GitHubRuntimeSettingsRecord, 1)
            if record is None:
                record = GitHubRuntimeSettingsRecord(id=1)
                session.add(record)
            record.local_first_guidance = policy.local_first_guidance
            record.local_git_transport_enabled = policy.local_git_transport_enabled
            record.remote_source_mutations_enabled = policy.remote_source_mutations_enabled
        return policy

    @_db_span("runtime.gitlab.get")
    async def get_gitlab_policy(self) -> GitLabRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(GitLabRuntimeSettingsRecord, 1)
            if record is None:
                record = GitLabRuntimeSettingsRecord(id=1)
                session.add(record)
                await session.flush()
            return GitLabRuntimePolicy(
                local_first_guidance=record.local_first_guidance,
                local_git_transport_enabled=record.local_git_transport_enabled,
                remote_source_mutations_enabled=record.remote_source_mutations_enabled,
            )

    @_db_span("runtime.gitlab.save")
    async def save_gitlab_policy(self, policy: GitLabRuntimePolicy) -> GitLabRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(GitLabRuntimeSettingsRecord, 1)
            if record is None:
                record = GitLabRuntimeSettingsRecord(id=1)
                session.add(record)
            record.local_first_guidance = policy.local_first_guidance
            record.local_git_transport_enabled = policy.local_git_transport_enabled
            record.remote_source_mutations_enabled = policy.remote_source_mutations_enabled
        return policy
