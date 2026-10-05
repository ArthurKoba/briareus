from __future__ import annotations

from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec


def verify_oauth_access_token(
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
