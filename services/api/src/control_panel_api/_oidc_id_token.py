"""Verify Rauthy OpenID Connect ID tokens; not Briareus Project grants.

The verified issuer/JWKS URL come from the trusted provider discovery
adapter, never an unverified token header, body or caller-provided URL.
"""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
import jwt
from pydantic import SecretStr


class OidcIdentityRejected(Exception):
    """ID token proof is absent, invalid, expired or incorrectly scoped."""


class OidcIdentityKeysUnavailable(Exception):
    """Trusted upstream JWKS metadata or signing keys cannot be verified."""


@dataclass(frozen=True, slots=True)
class VerifiedOidcIdentity:
    """Signed Rauthy OIDC identity, NOT an internal User/Project membership."""

    issuer: str
    subject: str
    client_id: str
    expires_at: datetime


_ALGORITHMS = frozenset({"EdDSA", "RS256", "RS384", "RS512"})


def _trusted_jwks_location(issuer: str, uri: str) -> bool:
    parent = urlsplit(issuer)
    key_uri = urlsplit(uri)
    return bool(
        parent.scheme == "https"
        and parent.hostname
        and parent.username is None
        and parent.password is None
        and not parent.query
        and not parent.fragment
        and issuer.endswith("/")
        and key_uri.scheme == "https"
        and key_uri.netloc == parent.netloc
        and key_uri.username is None
        and key_uri.password is None
        and not key_uri.query
        and not key_uri.fragment
        and key_uri.path.startswith(parent.path)
        and key_uri.path != parent.path
    )


async def verify_rauthy_id_token(
    token: SecretStr,
    *,
    expected_nonce: str,
    issuer: str,
    client_id: str,
    jwks_uri: str,
    client: httpx.AsyncClient,
) -> VerifiedOidcIdentity:
    """Require signed identity, exact client audience, nonce and bounded TTL.

    The calling BFF must atomically consume an approved state/PKCE transaction
    and later resolve an enabled Platform User/member. Neither this signature
    alone nor the returned subject authorizes any Briareus service operation.
    """
    raw = token.get_secret_value()
    if (
        not 80 <= len(raw) <= 8192
        or not isinstance(expected_nonce, str)
        or not 32 <= len(expected_nonce) <= 128
        or not client_id
        or not _trusted_jwks_location(issuer, jwks_uri)
    ):
        raise OidcIdentityRejected("OIDC ID token or trusted issuer proof missing")
    try:
        header = jwt.get_unverified_header(raw)
        kid = header.get("kid")
        alg = header.get("alg")
        if (
            not isinstance(kid, str)
            or not 1 <= len(kid) <= 128
            or alg not in _ALGORITHMS
            or header.get("crit")
            or any(f in header for f in ("jku", "jwk", "x5u", "x5c"))
        ):
            raise OidcIdentityRejected("ID token signing metadata rejected")
    except jwt.PyJWTError as exc:
        raise OidcIdentityRejected("malformed Rauthy ID token") from exc
    try:
        response = await client.get(
            jwks_uri,
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        response.raise_for_status()
        if len(response.content) > 65_536 or response.headers.get("content-type", "").split(";", 1)[
            0
        ].lower() not in {"application/json", "application/jwk-set+json"}:
            raise OidcIdentityKeysUnavailable("untrusted JWKS response")
        material = response.json()
        if not isinstance(material, dict):
            raise OidcIdentityKeysUnavailable("invalid JWKS object")
        keys = material.get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 16:
            raise OidcIdentityKeysUnavailable("signing keys unavailable")
        matching = [k for k in keys if isinstance(k, dict) and k.get("kid") == kid]
        if len(matching) != 1:
            raise OidcIdentityRejected("unknown or duplicate ID token key")
        key = matching[0]
        if (
            key.get("alg") != alg
            or key.get("use") != "sig"
            or (alg == "EdDSA" and (key.get("kty") != "OKP" or key.get("crv") != "Ed25519"))
            or (alg != "EdDSA" and key.get("kty") != "RSA")
            or any(k in key for k in ("jku", "x5u", "x5c", "x5t", "d"))
        ):
            raise OidcIdentityRejected("ID token signing key not trusted")
        jwk = jwt.PyJWK.from_dict(key, algorithm=alg)
    except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise OidcIdentityKeysUnavailable("issuer signing keys unavailable") from exc

    try:
        claims = jwt.decode(
            raw,
            jwk.key,
            algorithms=[alg],
            issuer=issuer,
            audience=client_id,
            leeway=0,
            options={"require": ["iss", "aud", "sub", "exp", "iat", "nonce"]},
        )
        subject = claims.get("sub")
        issued = claims.get("iat")
        expiry = claims.get("exp")
        if (
            not isinstance(subject, str)
            or not 1 <= len(subject) <= 256
            or claims.get("aud") != client_id
            or (claims.get("azp") is not None and claims.get("azp") != client_id)
            or not isinstance(issued, int)
            or isinstance(issued, bool)
            or not isinstance(expiry, int)
            or isinstance(expiry, bool)
            or not 0 < expiry - issued <= 3_600
            or not isinstance(claims.get("nonce"), str)
            or not hmac.compare_digest(claims["nonce"], expected_nonce)
        ):
            raise OidcIdentityRejected("ID token actor, audience or nonce mismatched")
        return VerifiedOidcIdentity(
            issuer=issuer,
            subject=subject,
            client_id=client_id,
            expires_at=datetime.fromtimestamp(expiry, tz=UTC),
        )
    except (jwt.PyJWTError, ValueError, TypeError, OverflowError) as exc:
        raise OidcIdentityRejected("Rauthy ID token invalid or expired") from exc
