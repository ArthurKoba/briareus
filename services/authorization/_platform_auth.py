"""Unpublished Admin bearer authentication backed by fresh Identity tables.

This is NOT the legacy OAuth transport and must never accept username cookies.
No live Admin BFF route is wired before C1-B/C2 verified service boundaries.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from common.platform_errors import AuthenticationRequired
from common.platform_ids import UserId
from common.settings import ProcessSettings
from identity._domain import User
from identity._persistence import AdminTokenRevocationRow
from identity._service import IdentityService

from ._project_access import AuthenticationMethod, CallerPrincipal

ISSUER = "mcp-bridge-platform-identity"
AUDIENCE = "mcp-bridge-platform-admin"
TTL = timedelta(minutes=15)


class AdminBearerSettings(ProcessSettings):
    signing_key: SecretStr = Field(validation_alias="PLATFORM_ADMIN_JWT_SIGNING_KEY")

    @field_validator("signing_key")
    @classmethod
    def _key_length(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode()) < 32:
            raise ValueError("PLATFORM_ADMIN_JWT_SIGNING_KEY needs >=32 random bytes")
        return value


class TokenClaims(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sub: UUID
    rev: int = Field(ge=1)
    jti: UUID
    iss: str
    aud: str
    iat: int
    nbf: int
    exp: int
    method: str
    purpose: str


@dataclass(frozen=True, slots=True)
class IssuedAdminToken:
    secret: SecretStr
    expires_at: datetime
    user_id: UserId


class PlatformAdminBearerAuth:
    def __init__(self, identity: IdentityService, settings: AdminBearerSettings) -> None:
        self.identity = identity
        self._signing_key = settings.signing_key.get_secret_value().encode()

    def _issue(self, user: User) -> IssuedAdminToken:
        now = datetime.now(UTC)
        expires = now + TTL
        token = jwt.encode(
            {
                "iss": ISSUER,
                "aud": AUDIENCE,
                "sub": str(user.id),
                "rev": user.credential_version,
                "method": AuthenticationMethod.LOCAL_LOGIN.value,
                "purpose": "admin",
                "iat": int(now.timestamp()),
                "nbf": int(now.timestamp()),
                "exp": int(expires.timestamp()),
                "jti": str(uuid4()),
            },
            self._signing_key,
            algorithm="HS256",
            headers={"typ": "JWT"},
        )
        return IssuedAdminToken(
            secret=SecretStr(token),
            expires_at=expires,
            user_id=user.id,
        )

    async def authenticate_local(
        self,
        username: str,
        password: str,
        *,
        source: str,
    ) -> IssuedAdminToken | None:
        user = await self.identity.authenticate_limited(
            username,
            password,
            source=source,
            pepper=self._signing_key,
        )
        if user is None:
            return None
        return self._issue(user)

    def _verified_claims(self, bearer: str) -> TokenClaims | None:
        if not (40 <= len(bearer) <= 8192):
            return None
        try:
            claims = jwt.decode(
                bearer,
                self._signing_key,
                algorithms=["HS256"],
                issuer=ISSUER,
                audience=AUDIENCE,
                options={
                    "require": [
                        "sub",
                        "rev",
                        "jti",
                        "iss",
                        "aud",
                        "iat",
                        "nbf",
                        "exp",
                        "method",
                        "purpose",
                    ]
                },
                leeway=0,
            )
            parsed = TokenClaims.model_validate(claims)
        except (jwt.PyJWTError, ValidationError, ValueError, TypeError):
            return None
        if (
            parsed.purpose != "admin"
            or parsed.method != AuthenticationMethod.LOCAL_LOGIN.value
            or parsed.iss != ISSUER
            or parsed.aud != AUDIENCE
        ):
            return None
        return parsed

    async def resolve(self, request: Request) -> CallerPrincipal | None:
        header = request.headers.get("authorization", "")
        parts = header.split(" ")
        if len(parts) != 2 or parts[0].casefold() != "bearer" or not parts[1]:
            return None
        claims = self._verified_claims(parts[1])
        if claims is None:
            return None
        async with self.identity.database.transaction() as tx:
            row = await self.identity.repository.get_user(tx, UserId(claims.sub))
            if (
                row is None
                or not row.enabled
                or row.deleted_at is not None
                or row.credential_version != claims.rev
            ):
                return None
            digest = hashlib.sha256(str(claims.jti).encode()).hexdigest()
            revoked = await tx.scalar(
                select(AdminTokenRevocationRow.jti_digest).where(
                    AdminTokenRevocationRow.jti_digest == digest
                )
            )
            if revoked is not None:
                return None
        return CallerPrincipal(
            user_id=UserId(claims.sub),
            authentication_method=AuthenticationMethod.LOCAL_LOGIN,
            credential_version=claims.rev,
            admin_jti_digest=digest,
        )

    async def revoke(self, bearer: str, *, caller: CallerPrincipal) -> None:
        claims = self._verified_claims(bearer)
        if claims is None or claims.sub != caller.user_id:
            raise AuthenticationRequired("invalid Admin credential")
        async with self.identity.database.transaction() as tx:
            row = await self.identity.repository.get_user(tx, UserId(claims.sub), lock=True)
            if row is None or not row.enabled or row.credential_version != claims.rev:
                raise AuthenticationRequired("stale Admin credential")
            await tx.execute(
                insert(AdminTokenRevocationRow)
                .values(
                    jti_digest=hashlib.sha256(str(claims.jti).encode()).hexdigest(),
                    user_id=claims.sub,
                    expires_at=datetime.fromtimestamp(claims.exp, UTC),
                    revoked_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(index_elements=["jti_digest"])
            )

    async def rotate(self, bearer: str, *, caller: CallerPrincipal) -> IssuedAdminToken:
        """One-use Admin JWT rotation with current role/revoke fencing."""
        claims = self._verified_claims(bearer)
        if claims is None or claims.sub != caller.user_id:
            raise AuthenticationRequired("invalid Admin credential")
        digest = hashlib.sha256(str(claims.jti).encode()).hexdigest()
        async with self.identity.database.transaction() as tx:
            row = await self.identity.repository.get_user(tx, UserId(claims.sub), lock=True)
            if (
                row is None
                or not row.enabled
                or row.deleted_at is not None
                or row.credential_version != claims.rev
            ):
                raise AuthenticationRequired("stale Admin credential")
            previous = await tx.scalar(
                select(AdminTokenRevocationRow.jti_digest)
                .where(AdminTokenRevocationRow.jti_digest == digest)
                .with_for_update()
            )
            if previous is not None:
                raise AuthenticationRequired("Admin credential already rotated")
            tx.add(
                AdminTokenRevocationRow(
                    jti_digest=digest,
                    user_id=row.id,
                    expires_at=datetime.fromtimestamp(claims.exp, UTC),
                    revoked_at=datetime.now(UTC),
                )
            )
            from identity._repository import to_user

            issued = self._issue(to_user(row))
            await tx.flush()
            return issued
