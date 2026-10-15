"""Server-held resource bearer paired with a verified Rauthy browser identity.

This credential is not a Platform User, service-peer proof or Cedar grant.
The actual Hand/Access must independently validate it for every effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import jwt
from pydantic import SecretStr

from ._oidc_id_token import OidcIdentityRejected, VerifiedOidcIdentity, _verified_provider_key
from ._oidc_origin_policy import validate_files_resource_intent


@dataclass(frozen=True, slots=True)
class PrivateOidcResourceCredential:
    issuer: str
    subject: str
    client_id: str
    audience: str
    expires_at: datetime
    bearer: SecretStr


async def verify_resource_credential(
    *,
    token: SecretStr,
    identity: VerifiedOidcIdentity,
    resource_audience: str,
    token_deadline: datetime,
    jwks_uri: str,
    client: httpx.AsyncClient,
) -> PrivateOidcResourceCredential:
    validate_files_resource_intent(
        issuer=identity.issuer, client_id=identity.client_id, resource_audience=resource_audience
    )
    raw = token.get_secret_value()
    key = await _verified_provider_key(
        raw, issuer=identity.issuer, jwks_uri=jwks_uri, client=client
    )
    try:
        claims = jwt.decode(
            raw,
            key.key,
            algorithms=[key.algorithm_name],
            issuer=identity.issuer,
            audience=resource_audience,
            leeway=0,
            options={"require": ["iss", "aud", "sub", "iat", "nbf", "exp", "azp", "typ", "jti"]},
        )
        aud = claims.get("aud")
        exp, issued, nbf = claims.get("exp"), claims.get("iat"), claims.get("nbf")
        jti = claims.get("jti")
        if (
            claims.get("sub") != identity.subject
            or claims.get("azp") != identity.client_id
            or claims.get("typ") != "Bearer"
            or claims.get("cnf") is not None
            or claims.get("act") is not None
            or not isinstance(aud, list)
            or len(aud) != 2
            or any(not isinstance(item, str) for item in aud)
            or set(aud) != {identity.client_id, resource_audience}
            or any(type(value) is not int for value in (exp, issued, nbf))
            or not 0 < exp - issued <= 86400
            or nbf >= exp
            or not isinstance(jti, str)
            or not 1 <= len(jti) <= 128
            or not jti.isascii()
            or any(ord(char) <= 32 or ord(char) >= 127 for char in jti)
        ):
            raise OidcIdentityRejected("resource token purpose or original identity mismatched")
        expires = min(identity.expires_at, token_deadline, datetime.fromtimestamp(exp, UTC))
        if expires <= datetime.now(UTC):
            raise OidcIdentityRejected("resource token lifetime already expired")
    except (jwt.PyJWTError, TypeError, ValueError, OverflowError):
        raise OidcIdentityRejected("Rauthy resource bearer rejected") from None
    return PrivateOidcResourceCredential(
        issuer=identity.issuer,
        subject=identity.subject,
        client_id=identity.client_id,
        audience=resource_audience,
        expires_at=expires,
        bearer=token,
    )
