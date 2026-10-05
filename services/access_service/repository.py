from __future__ import annotations

import json
import secrets
import time
from datetime import UTC, datetime

from sqlalchemy import select, update

from common.access_contracts import (
    AccessRequestView,
    AccountScope,
    EnforcementMode,
    SessionSnapshot,
)

from .database import (
    AccessDatabase,
    AccessRequestRecord,
    AgentSessionRecord,
    OAuthContextBlockRecord,
    SecurityEventRecord,
    SurfaceControlRecord,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _snapshot(record: AgentSessionRecord) -> SessionSnapshot:
    return SessionSnapshot(
        id=record.id,
        uid=record.uid,
        user_id=record.user_id,
        oauth_client_id=record.oauth_client_id,
        oauth_session_id=record.oauth_session_id,
        surface_id=record.surface_id,
        access_level=record.access_level,
        account_scope=record.account_scope,
        account_ids=list(json.loads(record.account_ids_json)),
        status=record.status,
        label=record.label,
        expires_at=record.expires_at,
    )


def _request_view(record: AccessRequestRecord) -> AccessRequestView:
    return AccessRequestView(
        id=record.id,
        session_id=record.session_id,
        kind=record.kind,
        status=record.status,
        requested_access_level=record.requested_access_level,
        requested_account_scope=record.requested_account_scope,
        requested_account_ids=list(json.loads(record.requested_account_ids_json)),
        requested_expires_at=record.requested_expires_at,
    )


class AccessRepository:
    def __init__(self, database: AccessDatabase) -> None:
        self.database = database

    async def open_session(
        self,
        *,
        user_id: str,
        client_id: str,
        oauth_session_id: str,
        surface_id: int,
        ttl_seconds: int,
        label: str,
    ) -> SessionSnapshot:
        uid = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + ttl_seconds
        record = AgentSessionRecord(
            uid=uid,
            user_id=user_id,
            oauth_client_id=client_id,
            oauth_session_id=oauth_session_id,
            surface_id=surface_id,
            access_level="read_only",
            account_scope="none",
            account_ids_json="[]",
            status="active",
            label=label,
            expires_at=expires_at,
        )
        async with self.database.sessions() as session:
            session.add(record)
            await session.flush()
            session.add(
                SecurityEventRecord(
                    user_id=user_id,
                    oauth_session_id=oauth_session_id,
                    session_id=record.id,
                    surface_id=surface_id,
                    event_type="session_opened",
                )
            )
            await session.commit()
            await session.refresh(record)
            return _snapshot(record)

    async def get_session_by_id(self, session_id: str) -> SessionSnapshot | None:
        async with self.database.sessions() as session:
            record = await session.get(AgentSessionRecord, session_id)
            return None if record is None else _snapshot(record)

    async def get_session(self, uid: str) -> SessionSnapshot | None:
        async with self.database.sessions() as session:
            record = await session.scalar(
                select(AgentSessionRecord).where(AgentSessionRecord.uid == uid)
            )
            if record is None:
                return None
            if (
                record.status == "active"
                and record.expires_at > 0
                and record.expires_at <= int(time.time())
            ):
                record.status = "expired"
                record.updated_at = _now()
                session.add(
                    SecurityEventRecord(
                        user_id=record.user_id,
                        oauth_session_id=record.oauth_session_id,
                        session_id=record.id,
                        surface_id=record.surface_id,
                        event_type="session_expired",
                    )
                )
                await session.commit()
            return _snapshot(record)

    async def touch_session(self, session_id: str) -> None:
        async with self.database.sessions() as session:
            await session.execute(
                update(AgentSessionRecord)
                .where(AgentSessionRecord.id == session_id)
                .values(last_used_at=_now())
            )
            await session.commit()

    async def update_label(self, session_id: str, label: str) -> SessionSnapshot | None:
        async with self.database.sessions() as session:
            record = await session.get(AgentSessionRecord, session_id)
            if record is None:
                return None
            record.label = label
            record.updated_at = _now()
            await session.commit()
            await session.refresh(record)
            return _snapshot(record)

    async def admin_update_session(
        self,
        session_id: str,
        *,
        admin_user_id: str,
        access_level: str | None,
        account_scope: str | None,
        account_ids: list[str] | None,
        expires_at: int | None,
        label: str | None,
    ) -> SessionSnapshot | None:
        now = _now()
        async with self.database.sessions() as session:
            record = await session.get(AgentSessionRecord, session_id)
            if record is None or record.user_id != admin_user_id:
                return None
            before = {
                "access_level": record.access_level,
                "account_scope": record.account_scope,
                "expires_at": record.expires_at,
            }
            if access_level is not None:
                record.access_level = access_level
            if account_scope is not None:
                record.account_scope = account_scope
                if account_scope != "selected":
                    record.account_ids_json = "[]"
            if account_ids is not None:
                record.account_ids_json = json.dumps(account_ids, separators=(",", ":"))
            if expires_at is not None:
                record.expires_at = expires_at
            if label is not None:
                record.label = label
            record.updated_at = now
            session.add(
                SecurityEventRecord(
                    user_id=record.user_id,
                    oauth_session_id=record.oauth_session_id,
                    session_id=record.id,
                    surface_id=record.surface_id,
                    event_type="session_admin_updated",
                    details_json=json.dumps(
                        {
                            "before": before,
                            "after": {
                                "access_level": record.access_level,
                                "account_scope": record.account_scope,
                                "expires_at": record.expires_at,
                            },
                        },
                        separators=(",", ":"),
                    ),
                )
            )
            await session.commit()
            await session.refresh(record)
            return _snapshot(record)

    async def revoke_session(
        self,
        session_id: str,
        *,
        event_type: str = "session_revoked",
    ) -> SessionSnapshot | None:
        now = _now()
        async with self.database.sessions() as session:
            record = await session.get(AgentSessionRecord, session_id)
            if record is None:
                return None
            if record.status != "revoked":
                record.status = "revoked"
                record.revoked_at = now
                record.updated_at = now
                session.add(
                    SecurityEventRecord(
                        user_id=record.user_id,
                        oauth_session_id=record.oauth_session_id,
                        session_id=record.id,
                        surface_id=record.surface_id,
                        event_type=event_type,
                    )
                )
                await session.commit()
                await session.refresh(record)
            return _snapshot(record)

    async def create_request(
        self,
        *,
        session_id: str,
        kind: str,
        requested_access_level: str = "",
        account_scope: AccountScope = "none",
        account_ids: list[str] | None = None,
        requested_expires_at: int = 0,
    ) -> AccessRequestView:
        account_ids = account_ids or []
        async with self.database.sessions() as session:
            existing = await session.scalar(
                select(AccessRequestRecord).where(
                    AccessRequestRecord.session_id == session_id,
                    AccessRequestRecord.kind == kind,
                    AccessRequestRecord.status == "pending",
                )
            )
            if existing is not None:
                return _request_view(existing)

            owner = await session.get(AgentSessionRecord, session_id)
            if owner is None:
                raise ValueError("agent session not found")
            record = AccessRequestRecord(
                session_id=session_id,
                kind=kind,
                status="pending",
                requested_access_level=requested_access_level,
                requested_account_scope=account_scope,
                requested_account_ids_json=json.dumps(account_ids, separators=(",", ":")),
                requested_expires_at=requested_expires_at,
            )
            session.add(record)
            session.add(
                SecurityEventRecord(
                    user_id=owner.user_id,
                    oauth_session_id=owner.oauth_session_id,
                    session_id=owner.id,
                    surface_id=owner.surface_id,
                    event_type=f"{kind}_requested",
                    details_json=json.dumps(
                        {
                            "account_scope": account_scope,
                            "account_ids": account_ids,
                            "requested_expires_at": requested_expires_at,
                        },
                        separators=(",", ":"),
                    ),
                )
            )
            await session.commit()
            await session.refresh(record)
            return _request_view(record)

    async def resolve_request(
        self,
        request_id: str,
        *,
        admin_user_id: str,
        approve: bool,
        account_scope: AccountScope | None,
        account_ids: list[str] | None,
        expires_at: int | None,
    ) -> tuple[AccessRequestView, SessionSnapshot]:
        now = _now()
        async with self.database.sessions() as session:
            request = await session.get(AccessRequestRecord, request_id)
            if request is None or request.status != "pending":
                raise ValueError("pending access request not found")
            owner = await session.get(AgentSessionRecord, request.session_id)
            if owner is None or owner.user_id != admin_user_id:
                raise ValueError("pending access request not found")

            if approve and request.kind == "full_access":
                scope = account_scope or request.requested_account_scope
                ids = (
                    account_ids
                    if account_ids is not None
                    else list(json.loads(request.requested_account_ids_json))
                )
                if scope == "selected" and not ids:
                    raise ValueError("selected account scope requires account_ids")
                if scope != "selected":
                    ids = []

            request.status = "approved" if approve else "rejected"
            request.resolved_by_user_id = admin_user_id
            request.resolved_at = now

            if approve and request.kind == "full_access":
                owner.access_level = "full_access"
                owner.account_scope = scope
                owner.account_ids_json = json.dumps(ids, separators=(",", ":"))
                owner.updated_at = now
                request.resolved_access_level = "full_access"
                request.resolved_account_scope = scope
                request.resolved_account_ids_json = json.dumps(ids, separators=(",", ":"))
            elif approve and request.kind == "extension":
                target = (
                    expires_at
                    if expires_at is not None
                    else request.requested_expires_at
                )
                owner.expires_at = target
                owner.updated_at = now
                request.resolved_expires_at = target

            session.add(
                SecurityEventRecord(
                    user_id=owner.user_id,
                    oauth_session_id=owner.oauth_session_id,
                    session_id=owner.id,
                    surface_id=owner.surface_id,
                    event_type=f"{request.kind}_{request.status}",
                    details_json=json.dumps(
                        {
                            "admin_user_id": admin_user_id,
                            "account_scope": request.resolved_account_scope,
                            "expires_at": request.resolved_expires_at,
                        },
                        separators=(",", ":"),
                    ),
                )
            )
            await session.commit()
            await session.refresh(request)
            await session.refresh(owner)
            return _request_view(request), _snapshot(owner)

    async def get_mode(self, user_id: str, surface_id: int) -> EnforcementMode:
        async with self.database.sessions() as session:
            record = await session.scalar(
                select(SurfaceControlRecord).where(
                    SurfaceControlRecord.user_id == user_id,
                    SurfaceControlRecord.surface_id == surface_id,
                )
            )
            return (
                record.mode  # type: ignore[return-value]
                if record is not None
                else "session_enforced"
            )

    async def set_mode(
        self,
        *,
        user_id: str,
        surface_id: int,
        mode: EnforcementMode,
    ) -> EnforcementMode:
        async with self.database.sessions() as session:
            record = await session.scalar(
                select(SurfaceControlRecord).where(
                    SurfaceControlRecord.user_id == user_id,
                    SurfaceControlRecord.surface_id == surface_id,
                )
            )
            if record is None:
                record = SurfaceControlRecord(
                    user_id=user_id,
                    surface_id=surface_id,
                    mode=mode,
                )
                session.add(record)
            else:
                record.mode = mode
                record.updated_at = _now()
            session.add(
                SecurityEventRecord(
                    user_id=user_id,
                    surface_id=surface_id,
                    event_type="session_control_changed",
                    details_json=json.dumps({"mode": mode}, separators=(",", ":")),
                )
            )
            await session.commit()
            return mode

    async def set_modes_batch(
        self,
        items: list[tuple[str, int, EnforcementMode]],
    ) -> list[tuple[str, int, EnforcementMode]]:
        now = _now()
        async with self.database.sessions() as session:
            for user_id, surface_id, mode in items:
                record = await session.scalar(
                    select(SurfaceControlRecord).where(
                        SurfaceControlRecord.user_id == user_id,
                        SurfaceControlRecord.surface_id == surface_id,
                    )
                )
                if record is None:
                    session.add(
                        SurfaceControlRecord(
                            user_id=user_id,
                            surface_id=surface_id,
                            mode=mode,
                            updated_at=now,
                        )
                    )
                else:
                    record.mode = mode
                    record.updated_at = now
                session.add(
                    SecurityEventRecord(
                        user_id=user_id,
                        surface_id=surface_id,
                        event_type="session_control_changed",
                        details_json=json.dumps({"mode": mode}, separators=(",", ":")),
                    )
                )
            await session.commit()
        return items

    async def list_sessions(self, user_id: str) -> list[SessionSnapshot]:
        async with self.database.sessions() as session:
            records = (
                await session.scalars(
                    select(AgentSessionRecord)
                    .where(AgentSessionRecord.user_id == user_id)
                    .order_by(AgentSessionRecord.updated_at.desc())
                    .limit(200)
                )
            ).all()
            return [_snapshot(record) for record in records]

    async def list_pending_requests(self, user_id: str) -> list[AccessRequestView]:
        async with self.database.sessions() as session:
            records = (
                await session.scalars(
                    select(AccessRequestRecord)
                    .join(
                        AgentSessionRecord,
                        AgentSessionRecord.id == AccessRequestRecord.session_id,
                    )
                    .where(
                        AgentSessionRecord.user_id == user_id,
                        AccessRequestRecord.status == "pending",
                    )
                    .order_by(AccessRequestRecord.created_at.desc())
                )
            ).all()
            return [_request_view(record) for record in records]

    async def block_oauth_context(
        self,
        *,
        oauth_session_id: str,
        user_id: str,
        reason: str,
    ) -> None:
        async with self.database.sessions() as session:
            existing = await session.get(OAuthContextBlockRecord, oauth_session_id)
            if existing is None:
                session.add(
                    OAuthContextBlockRecord(
                        oauth_session_id=oauth_session_id,
                        user_id=user_id,
                        reason=reason,
                    )
                )
                await session.commit()

    async def oauth_context_blocked(
        self, oauth_session_id: str, *, user_id: str
    ) -> bool:
        async with self.database.sessions() as session:
            record = await session.get(OAuthContextBlockRecord, oauth_session_id)
            return record is not None and record.user_id == user_id

    async def record_security_event(
        self,
        *,
        user_id: str,
        oauth_session_id: str,
        surface_id: int,
        event_type: str,
        details: dict[str, object] | None = None,
    ) -> None:
        async with self.database.sessions() as session:
            session.add(
                SecurityEventRecord(
                    user_id=user_id,
                    oauth_session_id=oauth_session_id,
                    surface_id=surface_id,
                    event_type=event_type,
                    details_json=json.dumps(details or {}, separators=(",", ":")),
                )
            )
            await session.commit()
