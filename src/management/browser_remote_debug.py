from __future__ import annotations

import hmac

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SALT = "koba-browser-remote-debug-v1"


class BrowserRemoteDebugAuthError(ValueError):
    """Remote browser debugging token is invalid or expired."""


def _serializer(secret: str) -> URLSafeTimedSerializer:
    if not secret:
        raise BrowserRemoteDebugAuthError("browser remote debug secret is not configured")
    return URLSafeTimedSerializer(secret_key=secret, salt=_SALT)


def issue_browser_remote_debug_token(secret: str, username: str, target_id: str) -> str:
    if not username or not target_id:
        raise BrowserRemoteDebugAuthError("browser remote debug identity is incomplete")
    return _serializer(secret).dumps({"sub": username, "target": target_id})


def verify_browser_remote_debug_token(
    token: str,
    secret: str,
    expected_username: str,
    expected_target_id: str,
    *,
    max_age_seconds: int = 300,
) -> None:
    try:
        payload = _serializer(secret).loads(token, max_age=max_age_seconds)
    except SignatureExpired as exc:
        raise BrowserRemoteDebugAuthError("browser remote debug token expired") from exc
    except BadSignature as exc:
        raise BrowserRemoteDebugAuthError("invalid browser remote debug token") from exc
    if not isinstance(payload, dict):
        raise BrowserRemoteDebugAuthError("invalid browser remote debug token payload")
    username = payload.get("sub")
    target_id = payload.get("target")
    if not isinstance(username, str) or not hmac.compare_digest(username, expected_username):
        raise BrowserRemoteDebugAuthError("browser remote debug subject mismatch")
    if not isinstance(target_id, str) or not hmac.compare_digest(target_id, expected_target_id):
        raise BrowserRemoteDebugAuthError("browser remote debug target mismatch")
