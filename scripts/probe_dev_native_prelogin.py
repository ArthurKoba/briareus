#!/usr/bin/env python3
"""Exercise ONE anonymous native Init -> PoW -> Cancel on the pinned public Dev.

Unlike probe_dev_native_auth.py's read-only GET checks, this explicit command
allocates and retires a short-lived anonymous Rauthy provider transaction via
the Briareus API. No account, password, OTP, token or Cedar grant is requested.
Never log the response bodies, provider challenge or transaction cookie.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.client import HTTPException
from http.cookiejar import CookieJar
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

ORIGIN = "https://briareus.koba-nexus.ru"
HOST = "briareus.koba-nexus.ru"
COOKIE = "__Host-briareus_native_transaction"
PATHS = frozenset(
    {
        "/api/v1/auth/start",
        "/api/v1/auth/pow",
        "/api/v1/auth/cancel",
    }
)
MAX_BODY = 8192
TIMEOUT = 12


@dataclass(frozen=True, slots=True)
class Reply:
    status: int
    document: dict[str, object] | None
    media_type: str
    no_store: bool
    no_cache: bool
    redirected: bool


class ProbeTransport(Protocol):
    def post(self, path: str) -> Reply: ...

    def pending(self) -> bool: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("ambiguous JSON")
        obj[key] = value
    return obj


class NativeAnonymousTransport:
    """Isolated memory-only cookie jar; no filesystem or shared browser."""

    def __init__(self) -> None:
        self._cookies = CookieJar()
        self._opener = build_opener(
            ProxyHandler({}), HTTPCookieProcessor(self._cookies), NoRedirect()
        )

    def pending(self) -> bool:
        cookies = list(self._cookies)
        return (
            len(cookies) == 1
            and cookies[0].name == COOKIE
            and cookies[0].domain == HOST
            and not cookies[0].domain_specified
            and cookies[0].path == "/"
            and cookies[0].secure
            and not cookies[0].is_expired()
            and 16 <= len(cookies[0].value) <= 256
        )

    def post(self, path: str) -> Reply:
        if path not in PATHS:
            raise ValueError("only pinned anonymous native paths permitted")
        request = Request(
            ORIGIN + path,
            data=b"{}",
            headers={
                "Host": HOST,
                "Origin": ORIGIN,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Content-Length": "2",
                "User-Agent": "Briareus-Dev-Anon-Prelogin/1",
            },
            method="POST",
        )
        try:
            reply = self._opener.open(request, timeout=TIMEOUT)
        except HTTPError as error:
            reply = error
        with reply:
            content = reply.read(MAX_BODY + 1)
            if len(content) > MAX_BODY:
                raise ValueError("provider reply exceeded bound")
            document: dict[str, object] | None = None
            if content:
                try:
                    parsed = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_pairs)
                    if isinstance(parsed, dict):
                        document = parsed
                except (ValueError, UnicodeError, RecursionError):
                    pass
            return Reply(
                status=reply.status,
                document=document,
                media_type=reply.headers.get_content_type(),
                no_store=reply.headers.get("cache-control") == "no-store",
                no_cache=reply.headers.get("pragma") == "no-cache",
                redirected=reply.status in range(300, 400) or bool(reply.headers.get("location")),
            )


def _safe_status(reply: Reply) -> bool:
    return (
        reply.media_type == "application/json"
        and reply.no_store
        and reply.no_cache
        and not reply.redirected
    )


def _start_valid(reply: Reply) -> bool:
    data = reply.document
    return (
        reply.status == 201
        and _safe_status(reply)
        and isinstance(data, dict)
        and set(data) == {"stage", "authenticated", "expires_in"}
        and data["stage"] == "first_factor_required"
        and data["authenticated"] is False
        and type(data["expires_in"]) is int
        and 1 <= data["expires_in"] <= 300
    )


def _pow_valid(reply: Reply) -> bool:
    data = reply.document
    if (
        reply.status != 200
        or not _safe_status(reply)
        or not isinstance(data, dict)
        or set(data) != {"challenge", "authenticated"}
        or data["authenticated"] is not False
    ):
        return False
    challenge = data["challenge"]
    return (
        isinstance(challenge, str)
        and 2 <= len(challenge) <= 128
        and challenge.isascii()
        and all(33 <= ord(char) <= 126 for char in challenge)
    )


def inspect(transport: ProbeTransport | None = None) -> dict[str, object]:
    client = NativeAnonymousTransport() if transport is None else transport
    result: dict[str, object] = {
        "scope": "exact Dev origin, single anonymous Init/PoW/Cancel, no credentials",
        "start_status": 0,
        "start_valid": False,
        "pending_cookie_scoped": False,
        "pow_status": 0,
        "pow_valid": False,
        "cancel_status": 0,
        "anonymous_transaction_retired": False,
        "user_password_or_otp_submitted": False,
        "signed_user_project_or_cedar_verified": False,
        "pass": False,
    }
    try:
        start = client.post("/api/v1/auth/start")
        result["start_status"] = start.status
        result["start_valid"] = _start_valid(start)
        result["pending_cookie_scoped"] = client.pending()
        if result["start_valid"] and result["pending_cookie_scoped"]:
            proof = client.post("/api/v1/auth/pow")
            result["pow_status"] = proof.status
            result["pow_valid"] = _pow_valid(proof)
    except (OSError, HTTPException, URLError, ValueError, TimeoutError, TypeError):
        # Never reflect upstream cookie/challenge/provider exception details.
        pass
    finally:
        try:
            if client.pending():
                canceled = client.post("/api/v1/auth/cancel")
                result["cancel_status"] = canceled.status
                result["anonymous_transaction_retired"] = (
                    canceled.status == 204
                    and canceled.document is None
                    and canceled.no_store
                    and canceled.no_cache
                    and not canceled.redirected
                    and not client.pending()
                )
        except (OSError, HTTPException, URLError, ValueError, TimeoutError, TypeError):
            pass
    result["pass"] = all(
        result[field] is True
        for field in (
            "start_valid",
            "pending_cookie_scoped",
            "pow_valid",
            "anonymous_transaction_retired",
        )
    )
    return result


def main() -> int:
    report = inspect()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
