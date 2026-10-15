#!/usr/bin/env python3
"""SAFE local-only Rauthy code+PKCE start inspection.

THIS creates one short-lived Valkey OIDC transaction by making GET /start,
but never follows Location, collects provider credentials, supplies a
password/code/verifier, or navigates to public Dev. Output is nonsecret only.

Passing this stage requires the Backend/Runtime owners to provide a proven
isolated https callback/client mapping; public Dev callback in a disposable
local provider is explicitly a blocker.
"""
from __future__ import annotations

import argparse
import hmac
import importlib.util
import json
import ssl
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

_ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("local_stack_readiness", _ROOT / "local-stack-readiness.py")
if _spec is None or _spec.loader is None:
    raise RuntimeError("Local readiness module unavailable")
_readiness = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _readiness
_spec.loader.exec_module(_readiness)

_STATE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_PKCE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
# Proof for the current disposable Rauthy client + safe return path must be
# separately accepted by Backend/Runtime before this becomes a success.
_APPROVED_ISOLATED_CALLBACKS: frozenset[str] = frozenset({
    "https://127.0.0.1:18446/api/auth/oidc/callback",
})
_LOCAL_BROWSER_ORIGIN = "https://127.0.0.1:18446"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def validate_start_headers(status: int, location: str, cookies: list[str]) -> dict[str, bool]:
    """Check structure, then assert the callback is owner-approved locally.

    Never expose Location, code_challenge, state, nonce, cookies or verifier
    to callers; only booleans are returned.
    """
    try:
        parsed = urlparse(location)
        port = parsed.port
    except ValueError:
        return {name: False for name in (
            "bff_start_302","provider_authorize_pinned",
            "s256_state_nonce_scope","host_only_transaction_cookie",
            "isolated_callback_accepted",
        )}
    parameters = parse_qs(parsed.query, keep_blank_values=True)
    expected = _readiness.EXPECTED_OIDC_LOCAL
    endpoint = urlparse(expected["authorization_endpoint"])
    allowed_keys = {
        "response_type", "client_id", "redirect_uri", "scope",
        "state", "nonce", "code_challenge", "code_challenge_method",
    }
    precise_query = set(parameters) == allowed_keys and all(len(a) == 1 for a in parameters.values())
    pkce = (
        precise_query
        and parameters.get("response_type") == ["code"]
        and parameters.get("code_challenge_method") == ["S256"]
        and _PKCE.fullmatch(parameters["code_challenge"][0]) is not None
        and _STATE.fullmatch(parameters["state"][0]) is not None
        and _STATE.fullmatch(parameters["nonce"][0]) is not None
        and "openid" in parameters["scope"][0].split()
        and not hmac.compare_digest(parameters["state"][0], parameters["nonce"][0])
    )
    uri_ok = (
        parsed.scheme == "https"
        and parsed.hostname == endpoint.hostname
        and port == endpoint.port
        and parsed.path == endpoint.path
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and parameters.get("client_id") == [expected["client_id"]]
    )
    cookie_parts = [part.strip() for part in cookies[0].split(";")] if len(cookies) == 1 else []
    raw_cookie_value = cookie_parts[0].partition("=")[2] if cookie_parts else ""
    flags = {part.lower() for part in cookie_parts[1:]}
    max_ages = [part.split("=",1)[1] for part in flags if part.startswith("max-age=")]
    # A transaction must be bound to this exact authorization state.
    cookie_ok = (
        len(cookies) == 1
        and cookie_parts[0].startswith("__Host-briareus_oidc_transaction=")
        and len(cookies[0]) <= 700
        and precise_query
        and _STATE.fullmatch(raw_cookie_value) is not None
        and hmac.compare_digest(raw_cookie_value, parameters["state"][0])
        and {"secure","httponly","samesite=lax","path=/"}.issubset(flags)
        and not any(part.startswith("domain=") for part in flags)
        and len(max_ages) == 1
        and max_ages[0].isascii() and max_ages[0].isdecimal()
        and 1 <= int(max_ages[0]) <= 300
    )
    callback = parameters.get("redirect_uri", [""])[0] if precise_query else ""
    callback_parsed = urlparse(callback)
    isolated = (
        callback in _APPROVED_ISOLATED_CALLBACKS
        and callback_parsed.scheme == "https"
        and callback_parsed.username is None
        and callback_parsed.password is None
        and callback_parsed.fragment == ""
        and callback_parsed.query == ""
    )
    return {
        "bff_start_302": status == 302,
        "provider_authorize_pinned": uri_ok,
        "s256_state_nonce_scope": pkce,
        "host_only_transaction_cookie": cookie_ok,
        "isolated_callback_accepted": isolated,
    }


def classify_start(status: int, checks: dict[str, bool],
                   *, check_provider: bool) -> tuple[str, bool]:
    """A structural 302 alone never proves a browser callback works."""
    structural = all(checks[k] for k in (
        "bff_start_302", "provider_authorize_pinned",
        "s256_state_nonce_scope", "host_only_transaction_cookie",
    ))
    if status in (502,503):
        stage = "backend_unavailable"
    elif not structural:
        stage = "invalid_start"
    elif not checks["isolated_callback_accepted"]:
        stage = "callback_not_isolated"
    elif not check_provider:
        stage = "isolated_listener_not_checked"
    elif not checks["provider_authorize_entry_200"]:
        stage = "provider_authorize_unavailable"
    elif not (checks["isolated_tls_ui_200"] and checks["isolated_bff_anonymous_401"]):
        stage = "isolated_listener_unavailable"
    else:
        stage = "accepted"
    return stage, check_provider and stage == "accepted"


def inspect_real_start(*, check_provider: bool = False,
                       source: str = "isolated-tls") -> dict[str, object]:
    """Use only explicit local origins; never follow a public callback.

    test-only self-signed TLS is accepted ONLY at fixed loopback ports
    18446 (Gateway callback) and 18444 (sandbox Rauthy provider). No
    arbitrary host/config/env input can opt into a trusted callback.
    """
    if source not in {"isolated-tls","gateway-legacy"}:
        raise ValueError("unrecognized fixed local OIDC source")
    isolated = source == "isolated-tls"
    url = (_LOCAL_BROWSER_ORIGIN if isolated else _readiness.GATEWAY) + "/api/v1/auth/authorize"
    browser_context = ssl._create_unverified_context() if isolated else None
    opener = build_opener(
        ProxyHandler({}),
        NoRedirect(),
        *([HTTPSHandler(context=browser_context)] if isolated else []),
    )
    req = Request(
        url,
        headers={"Host": "127.0.0.1:18446" if isolated else _readiness.PUBLIC_HOST,
                 "Accept": "text/html", "Cache-Control": "no-store"},
        method="GET",
    )
    try:
        with opener.open(req, timeout=9) as response:
            status, headers = response.status, response.headers
    except HTTPError as response:
        status, headers = response.code, response.headers
    except (TimeoutError, URLError):
        return {"stage": "LOCAL_OIDC_START", "state": "backend_unavailable", "ready": False}
    location = headers.get("Location", "")
    result = validate_start_headers(
        status, location, headers.get_all("Set-Cookie", []),
    )
    # Legacy public-Host Gateway is NOT the locally isolated TLS callback.
    # Only Backend's source-pinned test origin may qualify.
    if not isolated:
        result["isolated_callback_accepted"] = False
    # The source accepted callback URL is not enough: Runtime must have
    # a real fixed TLS loopback listener serving the Panel and BFF.
    if check_provider:
        result["isolated_tls_ui_200"] = False
        result["isolated_bff_anonymous_401"] = False
        if isolated and result["isolated_callback_accepted"]:
            local_opener = build_opener(
                ProxyHandler({}), NoRedirect(),
                HTTPSHandler(context=ssl._create_unverified_context()),
            )
            for path, name, expected_status in [
                ("/panel/", "isolated_tls_ui_200", 200),
                ("/api/v1/auth/session", "isolated_bff_anonymous_401", 401),
            ]:
                try:
                    with local_opener.open(
                        Request(_LOCAL_BROWSER_ORIGIN+path,method="GET"),
                        timeout=6,
                    ) as res:
                        reply_status=res.status
                        # Limit HTML read; never log or persist cookies/body.
                        if name=="isolated_tls_ui_200":
                            result[name] = b'id="app"' in res.read(8192) and reply_status==200
                        else:
                            result[name] = reply_status==expected_status
                except HTTPError as exc:
                    result[name] = exc.code==expected_status
                except (TimeoutError, URLError,ConnectionError):
                    result[name] = False
    if check_provider:
        accepted = all(result[k] for k in (
            "bff_start_302", "provider_authorize_pinned",
            "s256_state_nonce_scope", "host_only_transaction_cookie",
        ))
        provider_status = None
        if accepted:
            try:
                opener = build_opener(
                    ProxyHandler({}),
                    HTTPSHandler(context=ssl._create_unverified_context()),
                    NoRedirect(),
                )
                with opener.open(
                    Request(location, headers={"Accept": "text/html"}, method="GET"),
                    timeout=8,
                ) as provider:
                    provider_status = provider.status
            except HTTPError as exc:
                provider_status = exc.code
            except (TimeoutError, URLError, ConnectionError):
                provider_status = None
        result["provider_authorize_entry_200"] = provider_status == 200
    stage, verified = classify_start(status,result,check_provider=check_provider)
    return {
        "stage": "LOCAL_OIDC_START",
        "state": stage,
        "ready": verified,
        "checks": result,
        "real_user_token_accepted": False,
        "cedar_permit_accepted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--probe-provider-entry", action="store_true",
                        help="Verify sandbox authorize HTML and isolated HTTPS UI/session; never follow redirects")
    parser.add_argument("--source", choices=("isolated-tls","gateway-legacy"),
                        default="isolated-tls", help="Pinned Backend callback listener (default); old local public-Host transport is diagnostic only")
    args = parser.parse_args()
    result = inspect_real_start(check_provider=args.probe_provider_entry,source=args.source)
    if args.json:
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    else:
        print("LOCAL CODE+PKCE START — test-only transaction, NO provider redirect or credentials")
        print("STAGE", result["state"])
        if isinstance(result.get("checks"), dict):
            for key, valid in result["checks"].items():
                print(("PASS" if valid else "BLOCKED"), key)
        print("READY_FOR_SIGNED_USER_CALLBACK", result["ready"])
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    sys.exit(main())
