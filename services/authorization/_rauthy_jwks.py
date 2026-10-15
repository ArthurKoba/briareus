"""Verify Rauthy JWT signatures against an independently trusted issuer JWKS.

Cryptographic identity is not a Briareus User, Project membership, peer proof,
or Cedar Permit. The upstream key set is injected from verified HTTPS issuer
discovery by the future trusted attestor, never from a token URL/header.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import jwt


class RauthyTokenRejected(Exception):
    """Untrusted, invalid, incorrectly scoped, or expired provider token."""


class RauthyKeysUnavailable(Exception):
    """No currently trusted provider signing keys were supplied."""


@dataclass(frozen=True, slots=True)
class VerifiedRauthySubject:
    """Signed upstream identity; not an internal Briareus actor ID."""

    subject: str
    issuer: str
    audience: str
    expires_at: datetime


# Explicitly limited to algorithms present in verified Rauthy Development JWKS.
# Never derive an allowed algorithm from an untrusted JWT header alone.
_ALLOWED_ALGORITHMS = frozenset({"EdDSA", "RS256", "RS384", "RS512"})
_RAUTHY_USER_SUBJECT = re.compile(r"[A-Za-z0-9]{24}\Z", re.ASCII)


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("private authority response has duplicate field")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> object:
    raise ValueError("nonfinite number in private authority response")


def load_authority_json(body: bytes) -> object:
    """Parse bytes with one value per key at *every* JSON object depth.

    Callers already cap response lengths; no arbitrary URL/transport is
    selected by this utility and no IAM/User/Permit result is manufactured.
    """
    if not isinstance(body, bytes):
        raise ValueError("expected bounded response bytes")
    try:
        return json.loads(body, object_pairs_hook=_unique_fields, parse_constant=_reject_nonfinite)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("invalid private authority JSON") from None


class RauthyJwksVerifier:
    """Validate an expected resource-audience bearer with pretrusted keys.

    Caller must obtain JWKS from the configured issuer via authenticated HTTPS
    metadata, enforce key rotation policy and separately authenticate service
    peers and fresh Platform Project membership. A JWT is not authorization.
    """

    def __init__(
        self,
        *,
        issuer: str,
        resource_audience: str,
        oauth_client_id: str,
        trusted_jwks: dict[str, object],
    ) -> None:
        parsed = urlsplit(issuer)
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.hostname
            or not issuer.endswith("/")
            or not resource_audience
            or not oauth_client_id
            or resource_audience == oauth_client_id
        ):
            raise ValueError("Rauthy issuer and distinct resource audience required")
        self._issuer = issuer
        self._audience = resource_audience
        self._keys: dict[str, jwt.PyJWK] = {}
        raw_keys = trusted_jwks.get("keys")
        if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= 16:
            raise RauthyKeysUnavailable("Rauthy trusted JWKS key set missing or oversized")
        for entry in raw_keys:
            if not isinstance(entry, dict):
                raise RauthyKeysUnavailable("Rauthy JWK entry invalid")
            kid = entry.get("kid")
            alg = entry.get("alg")
            kty = entry.get("kty")
            if (
                not isinstance(kid, str)
                or not 1 <= len(kid) <= 128
                or kid in self._keys
                or not isinstance(alg, str)
                or alg not in _ALLOWED_ALGORITHMS
                or (alg == "EdDSA" and (kty != "OKP" or entry.get("crv") != "Ed25519"))
                or (alg != "EdDSA" and kty != "RSA")
                or entry.get("use") != "sig"
                or entry.get("key_ops") not in (None, ["verify"])
                or any(
                    key in entry
                    for key in ("jku", "x5u", "x5c", "x5t", "d", "p", "q", "dp", "dq", "qi", "oth")
                )
            ):
                raise RauthyKeysUnavailable("Rauthy trusted JWK metadata rejected")
            try:
                jwk = jwt.PyJWK.from_dict(entry, algorithm=alg)
            except (jwt.PyJWTError, TypeError, ValueError) as exc:
                raise RauthyKeysUnavailable("Rauthy trusted signing key rejected") from exc
            self._keys[kid] = jwk

    def verify_access_token(self, token: str) -> VerifiedRauthySubject:
        if not isinstance(token, str) or not 40 <= len(token) <= 8192:
            raise RauthyTokenRejected("Rauthy bearer invalid")
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            alg = header.get("alg")
            if (
                not isinstance(kid, str)
                or kid not in self._keys
                or alg != self._keys[kid].algorithm_name
                or header.get("crit")
                or any(name in header for name in ("jku", "jwk", "x5u", "x5c"))
            ):
                raise RauthyTokenRejected("Rauthy token signer not trusted")
            claims: dict[str, Any] = jwt.decode(
                token,
                key=self._keys[kid].key,
                algorithms=[self._keys[kid].algorithm_name],
                issuer=self._issuer,
                audience=self._audience,
                leeway=0,
                options={
                    "require": ["iss", "aud", "sub", "exp", "iat", "nbf", "typ", "azp", "jti"]
                },
            )
            sub = claims.get("sub")
            exp, issued, nbf = claims.get("exp"), claims.get("iat"), claims.get("nbf")
            client, jti = claims.get("azp"), claims.get("jti")
            audience = claims.get("aud")
            audiences = [audience] if isinstance(audience, str) else audience
            if (
                not isinstance(sub, str)
                or _RAUTHY_USER_SUBJECT.fullmatch(sub) is None
                or any(type(value) is not int for value in (exp, issued, nbf))
                or exp <= issued
                or nbf >= exp
                or claims.get("typ") != "Bearer"
                or claims.get("cnf") is not None
                or not isinstance(client, str)
                or not 1 <= len(client) <= 2048
                or not client.isascii()
                or any(char.isspace() for char in client)
                or not isinstance(jti, str)
                or not 1 <= len(jti) <= 128
                or not jti.isascii()
                or any(ord(char) <= 32 or ord(char) >= 127 for char in jti)
                or not isinstance(audiences, list)
                or not 1 <= len(audiences) <= 16
                or any(not isinstance(item, str) or not item for item in audiences)
                or len(set(audiences)) != len(audiences)
            ):
                raise RauthyTokenRejected("Rauthy signed subject invalid")
            return VerifiedRauthySubject(
                subject=sub,
                issuer=self._issuer,
                audience=self._audience,
                expires_at=datetime.fromtimestamp(exp, tz=UTC),
            )
        except (jwt.PyJWTError, TypeError, ValueError, OverflowError) as exc:
            raise RauthyTokenRejected("Rauthy bearer rejected") from exc
