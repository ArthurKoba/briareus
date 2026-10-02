from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time


class BrowserOperatorAuthError(ValueError):
    """Browser operator ticket is invalid or expired."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except Exception as exc:
        raise BrowserOperatorAuthError("invalid browser operator ticket encoding") from exc


def issue_browser_operator_ticket(
    secret: str,
    username: str,
    *,
    ttl_seconds: int = 300,
    now: int | None = None,
) -> str:
    if not secret or not username:
        raise BrowserOperatorAuthError("browser operator ticket configuration is incomplete")
    issued_at = int(time.time()) if now is None else now
    payload = json.dumps(
        {
            "sub": username,
            "exp": issued_at + ttl_seconds,
            "nonce": secrets.token_urlsafe(12),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = _b64encode(payload)
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_browser_operator_ticket(
    token: str,
    secret: str,
    expected_username: str,
    *,
    now: int | None = None,
) -> None:
    try:
        encoded, supplied_signature = token.split(".", 1)
    except ValueError as exc:
        raise BrowserOperatorAuthError("invalid browser operator ticket") from exc
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    supplied = _b64decode(supplied_signature)
    if not hmac.compare_digest(supplied, expected_signature):
        raise BrowserOperatorAuthError("invalid browser operator ticket signature")
    try:
        payload = json.loads(_b64decode(encoded))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BrowserOperatorAuthError("invalid browser operator ticket payload") from exc
    if not isinstance(payload, dict) or payload.get("sub") != expected_username:
        raise BrowserOperatorAuthError("browser operator ticket subject mismatch")
    expires_at = payload.get("exp")
    if not isinstance(expires_at, int):
        raise BrowserOperatorAuthError("browser operator ticket expiry is missing")
    current = int(time.time()) if now is None else now
    if expires_at < current:
        raise BrowserOperatorAuthError("browser operator ticket expired")
