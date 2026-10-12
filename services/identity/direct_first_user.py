"""Owner-local first-user REST service behind the internal Admin API.

No service-identity impersonation: direct HTTP is the deliberately selected
Briareus Development transport. Identity itself verifies User/JWT/JTI using
its own database. The per-process Ed25519 signer expires all sessions after
a restart; no key is exported and no uninvited first administrator is created.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from common.owner_bff_models import VerifiedAdminCaller
from common.platform_db import PlatformDatabase
from common.platform_ids import UserId
from common.private_user_token import (
    jti_digest,
    pinned_ed25519_kid,
    require_pinned_current_user_token,
)
from identity._domain import User
from identity._owner_ledger import OwnerCommandRow
from identity._persistence import AdminTokenRevocationRow
from identity._repository import IdentityRepository
from identity._service import IdentityService

_ISSUER = "briareus:identity"
_AUDIENCE = "briareus:panel"
_PURPOSE = "briareus-panel-user-v1"
_TYPE = "briareus-user-bearer+jwt"


class OriginalLoginUnavailable(Exception):
    """An original operation may already have issued a token; never replay."""


class SignedIdentityDenied(Exception):
    """A real invalid/disabled/expired/revoked User bearer, not DB unavailable."""


class DirectFirstUserIdentity:
    def __init__(self, *, identity: IdentityService, database: PlatformDatabase) -> None:
        if identity.database is not database or database.engine.url.database != "briareus_identity":
            raise ValueError("direct first-user sessions require the Identity owner database")
        self.identity = identity
        self.db = database
        self.repo = IdentityRepository()
        # Ephemeral deployment key: safe Dev bring-up, but invalidates all
        # sessions on a container restart. Future operator-pinned key support
        # requires an independent key custody/rotation decision.
        self._key = Ed25519PrivateKey.generate()
        self._kid = pinned_ed25519_kid(self._key.public_key())
        self._pepper = secrets.token_bytes(32)

    async def register(self, invitation: str, username: str, password: str) -> User:
        return await self.identity.register(
            invitation=invitation, username=username, password=password
        )

    async def _reserve_login(self, operation: UUID, username: str, source: str) -> UUID:
        digest = hmac.new(
            self._pepper,
            ("login:" + username.casefold() + ":" + source).encode(),
            hashlib.sha256,
        ).hexdigest()
        receipt = uuid4()
        now = datetime.now(UTC)
        statement = (
            insert(OwnerCommandRow)
            .values(
                id=receipt,
                operation_uuid=operation,
                actor_scope="identity:preauth",
                project_scope="none",
                operation="identity.login",
                key=str(operation),
                fingerprint=digest,
                expected_owner_revision="identity-first-user-http-v1",
                state="pending",
                encrypted_outcome=None,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(days=1),
            )
            .on_conflict_do_nothing()
            .returning(OwnerCommandRow.id)
        )
        async with self.db.transaction() as tx:
            if await tx.scalar(statement) is None:
                raise OriginalLoginUnavailable
        return receipt

    async def login(
        self, *, username: str, password: str, source: str, operation: UUID
    ) -> tuple[str, datetime]:
        user = await self.identity.authenticate_limited(
            username, password, source=source, pepper=self._pepper
        )
        if user is None or not user.enabled:
            raise SignedIdentityDenied
        receipt = await self._reserve_login(operation, username, source)
        async with self.db.transaction() as tx:
            current = await self.repo.get_user(tx, UserId(user.id), lock=True)
            if (
                current is None
                or not current.enabled
                or current.deleted_at is not None
                or current.credential_version != user.credential_version
            ):
                raise SignedIdentityDenied
            now = datetime.now(UTC)
            expires = now + timedelta(minutes=15)
            claims = {
                "iss": _ISSUER,
                "aud": _AUDIENCE,
                "sub": str(user.id),
                "jti": str(uuid4()),
                "credential_version": user.credential_version,
                "purpose": _PURPOSE,
                "iat": int(now.timestamp()),
                "nbf": int(now.timestamp()),
                "exp": int(expires.timestamp()),
            }
            encoded = jwt.encode(
                claims,
                self._key,
                algorithm="EdDSA",
                headers={"typ": _TYPE, "kid": self._kid},
            )
        # Failed completion is UNKNOWN. The already-reserved original must
        # not issue another bearer on retry.
        async with self.db.transaction() as tx:
            changed = await tx.scalar(
                update(OwnerCommandRow)
                .where(
                    OwnerCommandRow.id == receipt,
                    OwnerCommandRow.state == "pending",
                )
                .values(state="completed", updated_at=datetime.now(UTC))
                .returning(OwnerCommandRow.id)
            )
            if changed != receipt:
                raise OriginalLoginUnavailable
        return encoded, expires

    async def current(self, bearer: str) -> VerifiedAdminCaller:
        try:
            claims = require_pinned_current_user_token(
                bearer,
                pinned_public_key=self._key.public_key(),
                trusted_issuer=_ISSUER,
                trusted_audience=_AUDIENCE,
            )
        except Exception:
            raise SignedIdentityDenied from None

        async with self.db.transaction() as tx:
            row = await self.repo.get_user(tx, UserId(claims.sub))
            if (
                row is None
                or not row.enabled
                or row.deleted_at is not None
                or row.credential_version != claims.credential_version
            ):
                raise SignedIdentityDenied
            revoked = await tx.scalar(
                select(AdminTokenRevocationRow.jti_digest).where(
                    AdminTokenRevocationRow.jti_digest == jti_digest(claims.jti)
                )
            )
            if revoked is not None:
                raise SignedIdentityDenied
        return VerifiedAdminCaller(
            user_id=claims.sub,
            credential_version=claims.credential_version,
            source="verified-admin-bearer",
        )

    async def logout(self, bearer: str) -> None:
        await self.current(bearer)
        claims = require_pinned_current_user_token(
            bearer,
            pinned_public_key=self._key.public_key(),
            trusted_issuer=_ISSUER,
            trusted_audience=_AUDIENCE,
        )
        async with self.db.transaction() as tx:
            await tx.execute(
                insert(AdminTokenRevocationRow)
                .values(
                    jti_digest=jti_digest(claims.jti),
                    user_id=claims.sub,
                    expires_at=datetime.fromtimestamp(claims.exp, UTC),
                    revoked_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(index_elements=["jti_digest"])
            )
