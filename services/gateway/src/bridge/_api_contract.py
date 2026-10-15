"""Versioned Control Panel Auth API and source-pinned OAuth return boundary.

Every browser application auth endpoint belongs under /api/v1/auth.
The exact provider-registered callback is an OAuth redirect URI, NOT an API
alias. Its historical bytes cannot be changed by Gateway rewriting: that
requires the Rauthy client registration and Backend verifier together.
"""

from __future__ import annotations

from urllib.parse import unquote

AUTH_V1_PREFIX = "/api/v1/auth"
PUBLIC_API_V1_PREFIX = "/api/v1"
REGISTERED_RAUTHY_CALLBACK_PATH = "/api/auth/oidc/callback"
_RETIRED_AUTH_ROOT = "/api/auth"


def public_api_path(*, raw_path: str, decoded_path: object, method: str) -> bool:
    """Only exact v1 application paths or GET of the registered OAuth URI.

    Current Control Panel path parameters are canonical UUID/ASCII names.
    Encoded path segments belong to neither an approved v1 API route nor an
    alternative callback route. Query strings are independently preserved.
    """
    if raw_path == REGISTERED_RAUTHY_CALLBACK_PATH:
        return method == "GET" and decoded_path == raw_path
    return (
        isinstance(decoded_path, str)
        and raw_path == decoded_path
        and raw_path.startswith(PUBLIC_API_V1_PREFIX + "/")
        and "%" not in raw_path
        and "//" not in raw_path
        and all(segment not in {".", ".."} for segment in raw_path.split("/"))
    )


def retired_auth_path(*, raw_path: str, decoded_path: object, method: str) -> bool:
    """Deny unversioned auth except the one EXACT registered OAuth callback.

    Both raw ASGI URL and decoded route are inspected. Encoded aliases,
    double-encoded routes, near-callback suffixes and alternate historical
    endpoints never reach Backend. No auto-redirect or legacy translation.
    """
    if (
        method == "GET"
        and raw_path == REGISTERED_RAUTHY_CALLBACK_PATH
        and decoded_path == REGISTERED_RAUTHY_CALLBACK_PATH
    ):
        return False
    paths = [raw_path]
    if isinstance(decoded_path, str):
        paths.append(decoded_path)
    for path in paths:
        current = path
        for _ in range(4):
            if current == _RETIRED_AUTH_ROOT or current.startswith(_RETIRED_AUTH_ROOT + "/"):
                return True
            if "%" not in current:
                break
            try:
                decoded = unquote(current, encoding="utf-8", errors="strict")
            except UnicodeError:
                return current.startswith("/api/")
            if decoded == current:
                break
            current = decoded
    return False
