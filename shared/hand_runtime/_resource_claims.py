"""Purpose checks on SDK-verified Rauthy resource claims, before owner IO.

FastMCP remains responsible for the signature, configured issuer, audience
and trusted key source. A signed ID/Refresh or unsupported proof-bound token
is not a resource Bearer. These checks confer no Project/Cedar authority.
"""

from __future__ import annotations

import time
from typing import Any


def valid_resource_claims(claims: dict[str, Any]) -> bool:
    expires, issued, not_before = claims.get("exp"), claims.get("iat"), claims.get("nbf")
    subject, client, token_id = claims.get("sub"), claims.get("azp"), claims.get("jti")
    audience = claims.get("aud")
    audiences = [audience] if isinstance(audience, str) else audience
    now = time.time()
    return (
        all(type(value) is int for value in (expires, issued, not_before))
        and expires > now
        and expires > issued
        # Preserve the resource-token purpose ceiling of the owner BFF;
        # a verified signer cannot turn an anomalously long-lived bearer
        # into a permanent Hand resource authority.
        and expires - issued <= 86400
        and issued <= now
        and not_before <= now
        and not_before < expires
        and isinstance(subject, str)
        and 1 <= len(subject) <= 256
        and bool(subject.strip())
        and claims.get("typ") == "Bearer"
        and claims.get("cnf") is None
        and claims.get("act") is None
        and isinstance(client, str)
        and 1 <= len(client) <= 2048
        and client.isascii()
        and not any(character.isspace() for character in client)
        and isinstance(token_id, str)
        and 1 <= len(token_id) <= 128
        and token_id.isascii()
        and all(32 < ord(character) < 127 for character in token_id)
        and isinstance(audiences, list)
        and 1 <= len(audiences) <= 16
        and all(isinstance(item, str) and bool(item) for item in audiences)
        and len(set(audiences)) == len(audiences)
    )
