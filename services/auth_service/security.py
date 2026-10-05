from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

_ARGON2_ITERATIONS = 3
_ARGON2_LANES = 4
_ARGON2_MEMORY_KIB = 64 * 1024
_ARGON2_LENGTH = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    kdf = Argon2id(
        salt=salt,
        length=_ARGON2_LENGTH,
        iterations=_ARGON2_ITERATIONS,
        lanes=_ARGON2_LANES,
        memory_cost=_ARGON2_MEMORY_KIB,
    )
    return kdf.derive_phc_encoded(password.encode())


def verify_password(password: str, encoded: str) -> bool:
    try:
        Argon2id.verify_phc_encoded(password.encode(), encoded)
    except Exception:
        return False
    return True


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def random_token(bytes_count: int = 32) -> str:
    return secrets.token_urlsafe(bytes_count)


def load_private_key(pem: str) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise ValueError("AUTH_JWT_PRIVATE_KEY_PEM must contain a P-256 EC private key")
    return key


def load_public_key(pem: str) -> ec.EllipticCurvePublicKey:
    key = serialization.load_pem_public_key(pem.encode())
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise ValueError("AUTH_JWT_PUBLIC_KEY_PEM must contain a P-256 EC public key")
    return key


def public_jwk(public_key: ec.EllipticCurvePublicKey, *, kid: str) -> dict[str, str]:
    numbers = public_key.public_numbers()

    def encoded(value: int) -> str:
        raw = value.to_bytes(32, "big")
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return {
        "kty": "EC",
        "use": "sig",
        "alg": "ES256",
        "kid": kid,
        "crv": "P-256",
        "x": encoded(numbers.x),
        "y": encoded(numbers.y),
    }


def issue_access_token(
    *,
    private_key: ec.EllipticCurvePrivateKey,
    kid: str,
    issuer: str,
    audience: str,
    subject: str,
    username: str,
    client_id: str,
    scopes: list[str],
    session_id: str,
    ttl_seconds: int,
) -> tuple[str, int]:
    now = int(time.time())
    expires_at = now + ttl_seconds
    payload: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "username": username,
        "client_id": client_id,
        "scope": " ".join(scopes),
        "session_id": session_id,
        "jti": random_token(18),
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers={"kid": kid, "typ": "JWT"},
    )
    return token, expires_at


def verify_access_token(
    token: str,
    *,
    public_key: ec.EllipticCurvePublicKey,
    issuer: str,
    audience: str,
) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["ES256"],
            issuer=issuer,
            audience=audience,
            options={"require": ["iss", "aud", "sub", "client_id", "exp", "iat", "jti"]},
        )
    except jwt.PyJWTError:
        return None
    return payload if isinstance(payload, dict) else None


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def json_loads_object(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("expected JSON object")
    return loaded
