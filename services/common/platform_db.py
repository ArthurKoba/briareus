"""Fresh platform SQLAlchemy infrastructure; never touches historical DBs.

A composition root explicitly passes PLATFORM_DATABASE_URL. Metadata DDL
requires an operator-approved, disposable EMPTY database. No create_all in
normal application startup: Alembic baseline is intentionally still pending.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pydantic import Field, SecretStr, field_validator
from sqlalchemy import MetaData, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from common.platform_errors import Conflict, PersistenceTimeout
from common.settings import ProcessSettings


class PlatformDatabaseSettings(ProcessSettings):
    database_url: SecretStr = Field(validation_alias="PLATFORM_DATABASE_URL")
    invitation_secret_key: SecretStr = Field(validation_alias="PLATFORM_INVITATION_ENCRYPTION_KEY")
    idempotency_key: SecretStr = Field(validation_alias="PLATFORM_IDEMPOTENCY_ENCRYPTION_KEY")
    registration_base_url: str = Field(validation_alias="PLATFORM_REGISTRATION_BASE_URL")
    lock_timeout_ms: int = Field(
        default=3000,
        ge=500,
        le=15000,
        validation_alias="PLATFORM_DB_LOCK_TIMEOUT_MS",
    )
    statement_timeout_ms: int = Field(
        default=30000,
        ge=5000,
        le=120000,
        validation_alias="PLATFORM_DB_STATEMENT_TIMEOUT_MS",
    )

    @field_validator("registration_base_url")
    @classmethod
    def _secure_invite_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        normalized = value.strip()
        parsed = urlsplit(normalized)
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or len(normalized) > 2048
        ):
            raise ValueError("registration URL must not contain credentials or a query")
        if parsed.scheme == "https" and parsed.hostname:
            return normalized
        if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            return normalized
        raise ValueError("PLATFORM_REGISTRATION_BASE_URL must be HTTPS or local dev")


class PlatformBase(DeclarativeBase):
    metadata = MetaData()


class PlatformDatabase:
    def __init__(self, settings: PlatformDatabaseSettings) -> None:
        url = settings.database_url.get_secret_value()
        if not url.startswith("postgresql+asyncpg://"):
            raise ValueError("PLATFORM_DATABASE_URL must use postgresql+asyncpg")
        self._lock_timeout_ms = settings.lock_timeout_ms
        self._statement_timeout_ms = settings.statement_timeout_ms
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False, autoflush=False
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """A new AsyncSession and explicit commit/rollback on each invocation."""
        try:
            async with self.sessions() as session, session.begin():
                # A transaction waiting on the same idempotency/ownership row
                # must not tie up an HTTP worker indefinitely.
                await session.execute(
                    text("SELECT set_config('lock_timeout', :value, true)"),
                    {"value": f"{self._lock_timeout_ms}ms"},
                )
                await session.execute(
                    text("SELECT set_config('statement_timeout', :value, true)"),
                    {"value": f"{self._statement_timeout_ms}ms"},
                )
                yield session
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None)
            if sqlstate in {"55P03", "40P01", "40001"}:
                raise Conflict(
                    "transaction concurrency conflict; retry with the same key"
                ) from None
            if sqlstate == "57014":
                raise PersistenceTimeout("database operation deadline exceeded") from None
            raise

    async def close(self) -> None:
        await self.engine.dispose()
