"""Atomic command deduplication with encrypted replayable HTTP outcome.

One transaction includes the deduplication claim, business write, audit/outbox
and encrypted result. PostgreSQL's unique constraint serializes concurrent
claims. No Valkey-only idempotency or duplicate side effect after retry.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import SecretBytes, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from common.platform_errors import IdempotencyConflict, InvalidInput, OperationInProgress

from ._platform_persistence import IdempotencyRow

Command = Callable[[AsyncSession], Awaitable["CommandOutcome"]]
Reauthorize = Callable[[AsyncSession], Awaitable[None]]


@dataclass(frozen=True)
class CommandOutcome:
    status: int
    body: dict[str, Any]


def canonical_fingerprint(payload: object, *, secret: bytes) -> str:
    """HMAC real secret input, never Pydantic's constant ******** mask.

    Only a keyed digest of a SecretStr/SecretBytes participates in the
    canonical request hash. Neither plaintext nor a reversible secret value
    is persisted in the command ledger, audit or log output.
    """

    def encode_private(value: object) -> dict[str, str] | str:
        if isinstance(value, SecretStr):
            raw = value.get_secret_value().encode("utf-8")
        elif isinstance(value, SecretBytes):
            raw = value.get_secret_value()
        elif isinstance(value, UUID):
            return str(value)
        elif isinstance(value, (datetime, date)):
            return value.isoformat()
        else:
            raise TypeError("unsupported canonical request field type")
        return {"__private_hmac_v1__": hmac.new(secret, raw, hashlib.sha256).hexdigest()}

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=encode_private,
    ).encode()
    return hmac.new(secret, encoded, hashlib.sha256).hexdigest()


class IdempotentCommandExecutor:
    def __init__(self, database: PlatformDatabase, encryption_key: str) -> None:
        self.database = database
        self._cipher = Fernet(encryption_key.encode())
        self._fingerprint_secret = encryption_key.encode()

    @staticmethod
    def _verify_key(key: str) -> None:
        if not (1 <= len(key) <= 128) or not key.isascii() or not key.isprintable():
            raise InvalidInput("Idempotency-Key must be 1-128 printable ASCII characters")

    def _replay(self, row: IdempotencyRow, fingerprint: str) -> CommandOutcome:
        if row.fingerprint != fingerprint:
            raise IdempotencyConflict("idempotency key reused with different request")
        if row.status != "completed" or row.response_ciphertext is None:
            raise OperationInProgress("idempotent command has not completed")
        decoded = json.loads(self._cipher.decrypt(row.response_ciphertext.encode()))
        if not isinstance(decoded, dict):
            raise InvalidInput("stored command response is not an object")
        return CommandOutcome(row.response_status or 200, decoded)

    async def execute(
        self,
        *,
        actor_scope: str,
        project_scope: str,
        operation: str,
        key: str,
        payload: object,
        command: Command,
        reauthorize: Reauthorize,
    ) -> CommandOutcome:
        self._verify_key(key)
        fingerprint = canonical_fingerprint(payload, secret=self._fingerprint_secret)

        async def find(session: AsyncSession) -> IdempotencyRow | None:
            return cast(
                IdempotencyRow | None,
                await session.scalar(
                    select(IdempotencyRow)
                    .where(
                        IdempotencyRow.actor_scope == actor_scope,
                        IdempotencyRow.project_scope == project_scope,
                        IdempotencyRow.operation == operation,
                        IdempotencyRow.key == key,
                    )
                    .with_for_update()
                ),
            )

        try:
            async with self.database.transaction() as session:
                # Permission checks must also run before a persisted replay;
                # otherwise an excluded Team member could still retrieve a
                # previously stored variable/result using an old command key.
                await reauthorize(session)
                previous = await find(session)
                if previous is not None:
                    return self._replay(previous, fingerprint)
                row = IdempotencyRow(
                    actor_scope=actor_scope,
                    project_scope=project_scope,
                    operation=operation,
                    key=key,
                    fingerprint=fingerprint,
                    status="pending",
                    expires_at=datetime.now(UTC) + timedelta(days=7),
                )
                session.add(row)
                await session.flush()
                outcome = await command(session)
                row.status = "completed"
                row.response_status = outcome.status
                # Includes passwords/tokens on some successful commands:
                # encrypt response, never persist plaintext result.
                row.response_ciphertext = self._cipher.encrypt(
                    json.dumps(outcome.body, separators=(",", ":"), ensure_ascii=True).encode()
                ).decode()
                return outcome
        except IntegrityError:
            # Unique index collision concurrent with another invocation; the
            # database waited for its commit/rollback before resolving ours.
            async with self.database.transaction() as session:
                await reauthorize(session)
                previous = await find(session)
                if previous is None:
                    raise
                return self._replay(previous, fingerprint)
