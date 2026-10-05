from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from mcp.shared.auth import OAuthClientInformationFull
from sqlalchemy import delete, select, update

from .database import (
    AuthDatabase,
    AuthorizationCodeRecord,
    AuthorizationTransactionRecord,
    OAuthClientRecord,
    OAuthSessionRecord,
    RefreshTokenRecord,
    UserRecord,
)
from .security import hash_password, token_hash, verify_password


def _now() -> datetime:
    return datetime.now(UTC)


class AuthRepository:
    def __init__(self, database: AuthDatabase) -> None:
        self.database = database

    async def ensure_bootstrap_user(self, username: str, password: str) -> UserRecord:
        canonical = username.strip().casefold()
        async with self.database.sessions() as session:
            existing = await session.scalar(
                select(UserRecord).where(UserRecord.username == canonical)
            )
            if existing is not None:
                return existing
            record = UserRecord(
                username=canonical,
                password_hash=hash_password(password),
                enabled=True,
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def authenticate_user(self, username: str, password: str) -> UserRecord | None:
        canonical = username.strip().casefold()
        async with self.database.sessions() as session:
            record = await session.scalar(
                select(UserRecord).where(UserRecord.username == canonical)
            )
            if record is None or not record.enabled:
                return None
            if not verify_password(password, record.password_hash):
                return None
            return record

    async def get_user(self, user_id: str) -> UserRecord | None:
        async with self.database.sessions() as session:
            return await session.get(UserRecord, user_id)

    async def get_user_by_username(self, username: str) -> UserRecord | None:
        canonical = username.strip().casefold()
        async with self.database.sessions() as session:
            result = await session.scalars(
                select(UserRecord).where(UserRecord.username == canonical)
            )
            return result.first()

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with self.database.sessions() as session:
            record = await session.get(OAuthClientRecord, client_id)
            if record is None:
                return None
            return OAuthClientInformationFull.model_validate_json(record.payload_json)

    async def register_client(self, client: OAuthClientInformationFull) -> None:
        payload = client.model_dump_json(exclude_none=True)
        now = _now()
        async with self.database.sessions() as session:
            existing = await session.get(OAuthClientRecord, client.client_id)
            if existing is None:
                session.add(
                    OAuthClientRecord(
                        client_id=client.client_id,
                        payload_json=payload,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                existing.payload_json = payload
                existing.updated_at = now
            await session.commit()

    async def create_transaction(
        self,
        *,
        transaction_id: str,
        client_id: str,
        params: dict[str, Any],
        expires_at: datetime,
    ) -> None:
        async with self.database.sessions() as session:
            session.add(
                AuthorizationTransactionRecord(
                    id=transaction_id,
                    client_id=client_id,
                    params_json=json.dumps(params, ensure_ascii=False, separators=(",", ":")),
                    expires_at=expires_at,
                )
            )
            await session.commit()

    async def load_transaction(self, transaction_id: str) -> AuthorizationTransactionRecord | None:
        async with self.database.sessions() as session:
            record = await session.get(AuthorizationTransactionRecord, transaction_id)
            if record is None or record.expires_at <= _now():
                if record is not None:
                    await session.delete(record)
                    await session.commit()
                return None
            return record

    async def consume_transaction(
        self, transaction_id: str
    ) -> AuthorizationTransactionRecord | None:
        async with self.database.sessions() as session:
            record = await session.get(AuthorizationTransactionRecord, transaction_id)
            if record is None or record.expires_at <= _now():
                if record is not None:
                    await session.delete(record)
                    await session.commit()
                return None
            await session.delete(record)
            await session.commit()
            return record

    async def create_authorization_code(
        self,
        *,
        code: str,
        client_id: str,
        user_id: str,
        redirect_uri: str,
        redirect_uri_provided_explicitly: bool,
        scopes: list[str],
        resource: str,
        code_challenge: str,
        expires_at: datetime,
    ) -> None:
        async with self.database.sessions() as session:
            session.add(
                AuthorizationCodeRecord(
                    code=code,
                    client_id=client_id,
                    user_id=user_id,
                    redirect_uri=redirect_uri,
                    redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
                    scopes_json=json.dumps(scopes, separators=(",", ":")),
                    resource=resource,
                    code_challenge=code_challenge,
                    expires_at=expires_at,
                )
            )
            await session.commit()

    async def load_authorization_code(
        self, client_id: str, code: str
    ) -> AuthorizationCodeRecord | None:
        async with self.database.sessions() as session:
            record = await session.get(AuthorizationCodeRecord, code)
            if (
                record is None
                or record.client_id != client_id
                or record.consumed_at is not None
                or record.expires_at <= _now()
            ):
                return None
            return record

    async def consume_authorization_code(self, client_id: str, code: str) -> bool:
        now = _now()
        async with self.database.sessions() as session:
            result = await session.execute(
                update(AuthorizationCodeRecord)
                .where(
                    AuthorizationCodeRecord.code == code,
                    AuthorizationCodeRecord.client_id == client_id,
                    AuthorizationCodeRecord.consumed_at.is_(None),
                    AuthorizationCodeRecord.expires_at > now,
                )
                .values(consumed_at=now)
                .returning(AuthorizationCodeRecord.code)
            )
            consumed = result.scalar_one_or_none()
            await session.commit()
            return consumed is not None

    async def create_oauth_session(
        self, *, user_id: str, client_id: str, resource: str
    ) -> OAuthSessionRecord:
        record = OAuthSessionRecord(
            user_id=user_id,
            client_id=client_id,
            resource=resource,
            status="active",
        )
        async with self.database.sessions() as session:
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def oauth_session_active(
        self, session_id: str, *, user_id: str | None = None
    ) -> bool:
        async with self.database.sessions() as session:
            record = await session.get(OAuthSessionRecord, session_id)
            if record is None or record.status != "active":
                return False
            return user_id is None or record.user_id == user_id

    async def touch_oauth_session(self, session_id: str) -> None:
        async with self.database.sessions() as session:
            await session.execute(
                update(OAuthSessionRecord)
                .where(
                    OAuthSessionRecord.id == session_id,
                    OAuthSessionRecord.status == "active",
                )
                .values(last_used_at=_now())
            )
            await session.commit()

    async def revoke_oauth_session(self, session_id: str) -> None:
        now = _now()
        async with self.database.sessions() as session:
            await session.execute(
                update(OAuthSessionRecord)
                .where(OAuthSessionRecord.id == session_id)
                .values(status="revoked", revoked_at=now)
            )
            await session.execute(
                update(RefreshTokenRecord)
                .where(
                    RefreshTokenRecord.session_id == session_id,
                    RefreshTokenRecord.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await session.commit()

    async def store_refresh_token(
        self,
        *,
        token: str,
        session_id: str,
        client_id: str,
        user_id: str,
        scopes: list[str],
        resource: str,
        expires_at: datetime | None,
    ) -> None:
        async with self.database.sessions() as session:
            session.add(
                RefreshTokenRecord(
                    token_hash=token_hash(token),
                    session_id=session_id,
                    client_id=client_id,
                    user_id=user_id,
                    scopes_json=json.dumps(scopes, separators=(",", ":")),
                    resource=resource,
                    expires_at=expires_at,
                )
            )
            await session.commit()

    async def load_refresh_token(
        self, client_id: str, token: str
    ) -> RefreshTokenRecord | None:
        async with self.database.sessions() as session:
            record = await session.get(RefreshTokenRecord, token_hash(token))
            if record is None or record.client_id != client_id or record.revoked_at is not None:
                return None
            if record.expires_at is not None and record.expires_at <= _now():
                return None
            oauth_session = await session.get(OAuthSessionRecord, record.session_id)
            if oauth_session is None or oauth_session.status != "active":
                return None
            return record

    async def rotate_refresh_token(
        self, client_id: str, old_token: str
    ) -> RefreshTokenRecord | None:
        old_hash = token_hash(old_token)
        now = _now()
        async with self.database.sessions() as session:
            record = await session.get(RefreshTokenRecord, old_hash)
            if (
                record is None
                or record.client_id != client_id
                or record.revoked_at is not None
                or (record.expires_at is not None and record.expires_at <= now)
            ):
                return None
            oauth_session = await session.get(OAuthSessionRecord, record.session_id)
            if oauth_session is None or oauth_session.status != "active":
                return None
            result = await session.execute(
                update(RefreshTokenRecord)
                .where(
                    RefreshTokenRecord.token_hash == old_hash,
                    RefreshTokenRecord.revoked_at.is_(None),
                )
                .values(revoked_at=now)
                .returning(RefreshTokenRecord.token_hash)
            )
            if result.scalar_one_or_none() is None:
                await session.rollback()
                return None
            await session.commit()
            return record

    async def revoke_refresh_token(self, token: str) -> None:
        record_hash = token_hash(token)
        now = _now()
        async with self.database.sessions() as session:
            record = await session.get(RefreshTokenRecord, record_hash)
            if record is None:
                return
            await session.execute(
                update(RefreshTokenRecord)
                .where(RefreshTokenRecord.token_hash == record_hash)
                .values(revoked_at=now)
            )
            await session.execute(
                update(OAuthSessionRecord)
                .where(OAuthSessionRecord.id == record.session_id)
                .values(status="revoked", revoked_at=now)
            )
            await session.commit()

    async def purge_expired(self) -> None:
        now = _now()
        async with self.database.sessions() as session:
            await session.execute(
                delete(AuthorizationTransactionRecord).where(
                    AuthorizationTransactionRecord.expires_at <= now
                )
            )
            await session.execute(
                delete(AuthorizationCodeRecord).where(AuthorizationCodeRecord.expires_at <= now)
            )
            await session.commit()
