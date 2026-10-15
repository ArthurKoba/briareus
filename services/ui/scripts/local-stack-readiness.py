#!/usr/bin/env python3
"""Read-only, fixed-loopback Briareus UI/Gateway/OIDC acceptance gate.

Never uses credentials, browser cookies, tokens, secrets, writes or Dev APIs.
Passing is NOT proof of human login, Cedar authorization, or Files execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from urllib.error import HTTPError, URLError
from http.client import IncompleteRead
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from urllib.parse import urlparse

UI = "http://127.0.0.1:18929"
GATEWAY = "http://127.0.0.1:18925"
PUBLIC_HOST = "briareus.koba-nexus.ru"
ASSET = re.compile(rb"/panel/assets/index-[A-Za-z0-9_-]+\.js\b")

# Exact public issuer/client published by existing Briareus Development.
# Keep this distinct from the throwaway local provider: switching requires
# an explicit CLI profile and is never an automatic fallback.
EXPECTED_OIDC_DEV = {
    "issuer": "https://briareus.koba-nexus.ru/auth/v1/",
    "client_id": "briareus-control-panel",
    "authorization_endpoint": "https://briareus.koba-nexus.ru/auth/v1/oidc/authorize",
    "token_endpoint": "https://briareus.koba-nexus.ru/auth/v1/oidc/token",
    "userinfo_endpoint": "https://briareus.koba-nexus.ru/auth/v1/oidc/userinfo",
    "jwks_uri": "https://briareus.koba-nexus.ru/auth/v1/oidc/certs",
}

# Real pinned Rauthy 0.37.1 disposable instance on the SAME trusted local
# native Terminal host, never a Development or publicly exposed provider.
EXPECTED_OIDC_LOCAL = {
    "issuer": "https://localhost:18444/auth/v1/",
    "client_id": "briareus-local-panel",
    "authorization_endpoint": "https://localhost:18444/auth/v1/oidc/authorize",
    "token_endpoint": "https://localhost:18444/auth/v1/oidc/token",
    "userinfo_endpoint": "https://localhost:18444/auth/v1/oidc/userinfo",
    "jwks_uri": "https://localhost:18444/auth/v1/oidc/certs",
}
PROFILES = {"dev": EXPECTED_OIDC_DEV, "local-sandbox": EXPECTED_OIDC_LOCAL}


def valid_oidc_public_config(value: object, *, profile: str = "dev") -> bool:
    expected = PROFILES.get(profile)
    if not isinstance(value, dict) or not isinstance(expected, dict) or value != expected:
        return False
    allowed_host = "localhost" if profile == "local-sandbox" else "briareus.koba-nexus.ru"
    allowed_port = 18444 if profile == "local-sandbox" else 443
    for name, uri in value.items():
        if name == "client_id":
            continue
        parsed = urlparse(uri)
        if (parsed.scheme != "https" or parsed.hostname != allowed_host
                or (parsed.port or 443) != allowed_port or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            return False
    return True



class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Result:
    name: str
    status: int | None
    expected: str
    passed: bool


def request(url: str, *, gateway: bool = False, max_size: int = 512 * 1024) -> tuple[int | None, bytes]:
    if not (url.startswith(UI + "/") or url.startswith(GATEWAY + "/")):
        raise ValueError("Only fixed native loopback UI/Gateway peers may be checked")
    headers = {"Accept": "application/json,text/html;q=0.9", "Cache-Control": "no-store"}
    if gateway:
        headers["Host"] = PUBLIC_HOST
    req = Request(url, headers=headers, method="GET")
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=7) as resp:
            return resp.status, resp.read(max_size + 1)
    except HTTPError as exc:
        # A Gateway 503 can arrive before its chunked error body finishes.
        # Keep the actual status without publishing upstream body details.
        try:
            body = exc.read(256)
        except (IncompleteRead, ConnectionError, TimeoutError):
            body = b""
        return exc.code, body
    except (IncompleteRead, TimeoutError, URLError, ConnectionError):
        return None, b""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Print status JSON without response bodies")
    parser.add_argument("--profile", choices=tuple(PROFILES), default="dev",
                        help="Explicit expected issuer/client; never auto-detect or downgrade")
    args = parser.parse_args()
    results: list[Result] = []

    def add(name: str, status: int | None, expected: str, passed: bool) -> None:
        results.append(Result(name, status, expected, passed))

    direct_status, direct_html = request(UI + "/panel/")
    direct_asset = ASSET.search(direct_html) if direct_status == 200 else None
    add("ui_local_html", direct_status, "200 with hashed /panel/ JS", bool(direct_asset))

    asset_path = direct_asset.group().decode("ascii") if direct_asset else ""
    direct_js_status, direct_js = request(UI + asset_path) if asset_path else (None, b"")
    add("ui_local_bundle", direct_js_status, "200 nonempty <=512 KiB", direct_js_status == 200 and 1000 < len(direct_js) <= 512 * 1024)

    proxy_status, proxy_html = request(GATEWAY + "/panel/", gateway=True)
    proxy_asset = ASSET.search(proxy_html) if proxy_status == 200 else None
    add("gateway_ui_html", proxy_status, "same hashed JS reference", proxy_asset is not None and proxy_asset.group() == (direct_asset.group() if direct_asset else b""))

    proxy_js_status, proxy_js = request(GATEWAY + asset_path, gateway=True) if asset_path else (None, b"")
    add("gateway_ui_bundle", proxy_js_status, "byte-identical JS via Gateway", proxy_js_status == 200 and direct_js_status == 200 and hashlib.sha256(proxy_js).digest() == hashlib.sha256(direct_js).digest())

    for name, path in [("rauthy_gateway_health", "/auth/v1/health"), ("rauthy_gateway_jwks", "/auth/v1/oidc/certs")]:
        status, body = request(GATEWAY + path, gateway=True)
        add(name, status, "HTTP 200 public response", status == 200 and 0 < len(body) <= 512 * 1024)

    config_status, config = request(GATEWAY + "/api/v1/auth/config", gateway=True)
    config_shape = False
    if config_status == 200:
        try:
            obj = json.loads(config)
            config_shape = valid_oidc_public_config(obj, profile=args.profile)
        except (UnicodeDecodeError, ValueError):
            pass
    add("oidc_bff_public_config", config_status, "200 with exact issuer/client and source-pinned authorize/token/userinfo/JWKS endpoints", config_shape)

    for name, path in [("oidc_bff_anonymous_session", "/api/v1/auth/session"), ("oidc_bff_anonymous_platform", "/api/v1/auth/me")]:
        status, _ = request(GATEWAY + path, gateway=True)
        add(name, status, "401 without login cookie; 200 is fail-open", status == 401)

    ready = all(item.passed for item in results)
    out = {"stage": "LOCAL_HTTP_ONLY", "profile": args.profile,
           "ready_for_real_login_acceptance": ready,
           "live_human_auth_confirmed": False, "cedar_permit_confirmed": False,
           "checks": {item.name: asdict(item) for item in results}}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"LOCAL NATIVE OIDC CHECKPOINT — profile={args.profile}, no credentialed operations")
        for item in results:
            print(f"{'PASS' if item.passed else 'BLOCKED'} {item.name}: observed={item.status}, required={item.expected}")
        print("READY_FOR_REAL_LOGIN_ACCEPTANCE", ready)
    return 0 if ready else 2


if __name__ == "__main__":
    sys.exit(main())
