"""Identity-owned source issuer and live revocation of one private User bearer.

Private release-injected Ed25519 key never leaves Identity. The Admin API,
Panel and Gateway receive only release-pinned public key and must re-check
current Identity state via a separately authenticated source port.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from common.owner_contracts import OwnerAuthorityUnavailable
from common.platform_db import PlatformDatabase
from common.platform_ids import UserId
from common.private_user_token import (
    jti_digest,
    pinned_ed25519_kid,
    require_pinned_current_user_token,
)
from identity._domain import User
from identity._persistence import AdminTokenRevocationRow
from identity._repository import IdentityRepository
from identity.private_login_source import (
    IssuedIdentityBearer,
    VerifiedIdentityLoginAdmission,
)

_TYPE = "briareus-user-bearer+jwt"
_PURPOSE = "briareus-panel-user-v1"


class IdentityPrivateUserSessionIssuer:
    """Release-pinned bearer issuer with CURRENT Identity SQL revalidation."""

    def __init__(
        self,
        *,
        database: PlatformDatabase,
        signing_key_pem: SecretStr,
        issuer: str,
        audience: str,
        recipient_service_id: UUID,
        recipient_instance_uuid: UUID,
    ) -> None:
        if (
            database.engine.url.database != "briareus_identity"
            or not issuer.startswith("briareus:")
            or not audience.startswith("briareus:")
            or recipient_service_id.version != 4
            or recipient_instance_uuid.version != 4
        ):
            raise ValueError("trusted Identity User issuer requires own DB and C2 service")
        try:
            key = serialization.load_pem_private_key(
                signing_key_pem.get_secret_value().encode(), password=None
            )
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("Identity bearer key must be Ed25519")
        except (TypeError, ValueError):
            raise ValueError("invalid private Identity release signing key") from None
        self._db = database
        self._repo = IdentityRepository()
        self._key = key
        self._kid = pinned_ed25519_kid(key.public_key())
        self._issuer = issuer
        self._audience = audience
        self._recipient = (recipient_service_id, recipient_instance_uuid)

    def matches_accepted_identity_source(
        self,
        *,
        database: PlatformDatabase,
        public_key: Ed25519PublicKey,
        issuer: str,
        audience: str,
    ) -> bool:
        """One release pin and SAME owner DB for issuance and current-reader."""
        return (
            self._db is database
            and self._kid == pinned_ed25519_kid(public_key)
            and self._issuer == issuer
            and self._audience == audience
        )

    def _connection(self, admission: VerifiedIdentityLoginAdmission) -> None:
        if not isinstance(admission, VerifiedIdentityLoginAdmission):
            raise OwnerAuthorityUnavailable("current Identity login source unavailable")
        peer = admission.recipient
        if (
            peer.service_id != self._recipient[0]
            or peer.instance_uuid != self._recipient[1]
            or peer.audience != "briareus:identity"
            or admission.expires_at <= datetime.now(UTC)
            or peer.expires_at <= datetime.now(UTC)
        ):
            raise OwnerAuthorityUnavailable("Identity User bearer has no accepted C2 peer")

    async def issue_for_current_user(
        self, *, user: User, admission: VerifiedIdentityLoginAdmission
    ) -> IssuedIdentityBearer:
        self._connection(admission)
        # Serialize issue with disable/delete/password-rotation on the
        # authoritative Identity row. The token is then re-read immediately.
        async with self._db.transaction() as tx:
            current = await self._repo.get_user(tx, UserId(user.id), lock=True)
            if (
                current is None
                or current.deleted_at is not None
                or not current.enabled
                or current.credential_version != user.credential_version
            ):
                raise OwnerAuthorityUnavailable("Identity User changed before session issue")
            now = datetime.now(UTC)
            expiry = now + timedelta(minutes=15)
            jti = uuid4()
            payload = {
                "iss": self._issuer,
                "aud": self._audience,
                "sub": str(user.id),
                "jti": str(jti),
                "credential_version": user.credential_version,
                "purpose": _PURPOSE,
                "iat": int(now.timestamp()),
                "nbf": int(now.timestamp()),
                "exp": int(expiry.timestamp()),
            }
            signed = jwt.encode(
                payload,
                self._key,
                algorithm="EdDSA",
                headers={"typ": _TYPE, "kid": self._kid},
            )
            return IssuedIdentityBearer(
                token=SecretStr(signed),
                subject_user_id=user.id,
                jti=jti,
                credential_version=user.credential_version,
                issuer=self._issuer,
                audience=self._audience,
                issued_at=now,
                expires_at=expiry,
            )

    async def require_current(
        self, *, issued: IssuedIdentityBearer, admission: VerifiedIdentityLoginAdmission
    ) -> None:
        self._connection(admission)
        claims = require_pinned_current_user_token(
            issued.token.get_secret_value(),
            pinned_public_key=self._key.public_key(),
            trusted_issuer=self._issuer,
            trusted_audience=self._audience,
        )
        if (
            claims.sub != issued.subject_user_id
            or claims.jti != issued.jti
            or claims.credential_version != issued.credential_version
        ):
            raise OwnerAuthorityUnavailable("Identity issued credential subject changed")
        async with self._db.transaction() as tx:
            row = await self._repo.get_user(tx, UserId(claims.sub))
            if (
                row is None
                or row.deleted_at is not None
                or not row.enabled
                or row.credential_version != claims.credential_version
            ):
                raise OwnerAuthorityUnavailable("Identity User credential revoked")
            revoked = await tx.scalar(
                select(AdminTokenRevocationRow.jti_digest).where(
                    AdminTokenRevocationRow.jti_digest == jti_digest(claims.jti)
                )
            )
            if revoked is not None:
                raise OwnerAuthorityUnavailable("Identity User JTI revoked")

    async def revoke_user_token(
        self, *, bearer: SecretStr, admission: VerifiedIdentityLoginAdmission
    ) -> None:
        """One token JTI revocation; no password or bearer persisted."""
        self._connection(admission)
        claims = require_pinned_current_user_token(
            bearer.get_secret_value(),
            pinned_public_key=self._key.public_key(),
            trusted_issuer=self._issuer,
            trusted_audience=self._audience,
        )
        async with self._db.transaction() as tx:
            current = await self._repo.get_user(tx, UserId(claims.sub), lock=True)
            if current is None or current.deleted_at is not None:
                raise OwnerAuthorityUnavailable("Identity owner User unavailable")
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
