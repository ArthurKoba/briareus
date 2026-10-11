"""Release-pinned Ed25519 short-lived User bearer for one private Admin API.

Pure crypto here is NOT current Identity/Team/Project authorization. Consumers
must independently check live Identity enabled/version/JTI revocation and
current Control/Access/AgentSession grants over authenticated service transport.
No cross-owner SQL, signing key in Gateway, or token in logs.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from common.owner_contracts import OwnerAuthorityUnavailable

_TYPE = "briareus-user-bearer+jwt"
_PURPOSE = "briareus-panel-user-v1"
_MAX_SECONDS = 900


class IdentityCredentialRejected(OwnerAuthorityUnavailable):
    """ONLY verified Identity-owner source can assert a token is denied.

    Network/SQL/C2 lookup failures are NOT proof of authentication denial.
    This is a private trusted type; unknown/unverified failures stay 503.
    """


class PrivateUserTokenClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    iss: str
    aud: str
    sub: UUID
    jti: UUID
    credential_version: int = Field(ge=1)
    purpose: str
    iat: int
    nbf: int
    exp: int


def pinned_ed25519_kid(key: Ed25519PublicKey) -> str:
    return hashlib.sha256(
        key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).hexdigest()


def require_pinned_current_user_token(
    bearer: str,
    *,
    pinned_public_key: Ed25519PublicKey,
    trusted_issuer: str,
    trusted_audience: str,
) -> PrivateUserTokenClaims:
    """Verify signature, exact token format, short TTL and UUIDv4.

    The issuer/audience/key MUST be pinned from accepted release authority;
    an incoming JWT key id, JWKS URL, Host or previous bearer is not a pin.
    """
    if (
        not 40 <= len(bearer) <= 8192
        or not trusted_issuer
        or not trusted_audience
        or not isinstance(pinned_public_key, Ed25519PublicKey)
    ):
        raise OwnerAuthorityUnavailable("trusted Identity User bearer pin unavailable")
    try:
        header = jwt.get_unverified_header(bearer)
        if (
            header.get("alg") != "EdDSA"
            or header.get("typ") != _TYPE
            or header.get("kid") != pinned_ed25519_kid(pinned_public_key)
            or header.get("crit")
        ):
            raise OwnerAuthorityUnavailable("Identity bearer signer or algorithm not pinned")
        raw = jwt.decode(
            bearer,
            pinned_public_key,
            algorithms=["EdDSA"],
            issuer=trusted_issuer,
            audience=trusted_audience,
            leeway=0,
            options={
                "require": [
                    "iss",
                    "aud",
                    "sub",
                    "jti",
                    "credential_version",
                    "purpose",
                    "iat",
                    "nbf",
                    "exp",
                ]
            },
        )
        claims = PrivateUserTokenClaims.model_validate_json(
            json.dumps(raw, separators=(",", ":"), allow_nan=False)
        )
        now = int(datetime.now(UTC).timestamp())
        if (
            claims.iss != trusted_issuer
            or claims.aud != trusted_audience
            or claims.purpose != _PURPOSE
            or claims.sub.version != 4
            or claims.jti.version != 4
            or not claims.iat <= claims.nbf <= now < claims.exp
            or claims.exp - claims.iat > _MAX_SECONDS
            or claims.iat > now
        ):
            raise OwnerAuthorityUnavailable("Identity bearer no longer current or scoped")
        return claims
    except (jwt.PyJWTError, ValidationError, KeyError, ValueError, TypeError):
        raise OwnerAuthorityUnavailable("Identity bearer invalid or expired") from None


def jti_digest(jti: UUID) -> str:
    if not isinstance(jti, UUID) or jti.version != 4:
        raise OwnerAuthorityUnavailable("User bearer JTI invalid")
    return hashlib.sha256(str(jti).encode("ascii")).hexdigest()
