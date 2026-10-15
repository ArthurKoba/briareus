#!/usr/bin/env python3
"""Bounded public Development native-login ingress check; no credentials.

Source and deployment readiness are different. This probe never follows
redirects, submits a password, reads an operator secret, or claims a Cedar
Permit. One pinned public Briareus Development origin, explicit GETs only.
"""

from __future__ import annotations

import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ORIGIN = "https://briareus.koba-nexus.ru"
ISSUER = ORIGIN + "/auth/v1/"
MAX_BYTES = 8192
TIMEOUT = 7
PATHS = (
    "/panel/",
    "/api/v1/auth/capabilities",
    "/api/auth/native/capabilities",
    "/auth/v1/.well-known/openid-configuration",
    "/auth/v1/users",
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def get_statuses() -> dict[str, tuple[int, str, bytes, bool]]:
    """Sanitize observations: only bounded response, no cookies or headers."""
    opener = build_opener(ProxyHandler({}), NoRedirect())
    readings: dict[str, tuple[int, str, bytes, bool]] = {}
    for path in PATHS:
        request = Request(
            ORIGIN + path,
            headers={
                "Accept": "application/json, text/html",
                "User-Agent": "Briareus-Dev-Native-Readiness/1",
            },
            method="GET",
        )
        try:
            with opener.open(request, timeout=TIMEOUT) as response:
                status = response.status
                content_type = response.headers.get_content_type()
                body = response.read(MAX_BYTES + 1)
                redirected = bool(response.headers.get("location"))
        except HTTPError as error:
            with error:
                status = error.code
                content_type = error.headers.get_content_type()
                body = error.read(MAX_BYTES + 1)
                redirected = bool(error.headers.get("location"))
        except (OSError, HTTPException, URLError):
            readings[path] = (0, "unavailable", b"", False)
            continue
        readings[path] = (status, content_type, body, redirected)
    return readings


def review(readings: dict[str, tuple[int, str, bytes, bool]]) -> dict[str, object]:
    if set(readings) != set(PATHS):
        raise ValueError("missing or extra public readiness probes")
    html = readings["/panel/"]
    capability = readings["/api/v1/auth/capabilities"]
    obsolete = readings["/api/auth/native/capabilities"]
    oidc = readings["/auth/v1/.well-known/openid-configuration"]
    private = readings["/auth/v1/users"]
    flags = {
        "panel_html": html[0] == 200 and html[1] == "text/html" and not html[3],
        "native_v1_capabilities": False,
        "obsolete_native_route_closed": obsolete[0] in {404, 410} and not obsolete[3],
        "rauthy_discovery_issuer": False,
        "provider_admin_routes_private": private[0] == 404 and not private[3],
    }
    if (
        capability[0] == 200
        and capability[1] == "application/json"
        and len(capability[2]) <= MAX_BYTES
    ):
        try:
            document = json.loads(capability[2])
        except (ValueError, TypeError):
            document = None
        if isinstance(document, dict):
            flags["native_v1_capabilities"] = (
                document.get("protocol") == "rauthy-native-v1"
                and document.get("first_factor") == "password"
                and document.get("pow") == "client-solved"
                and document.get("cancel") is True
                and isinstance(document.get("continuations"), list)
                and not capability[3]
            )
    if oidc[0] == 200 and oidc[1] == "application/json" and len(oidc[2]) <= MAX_BYTES:
        try:
            document = json.loads(oidc[2])
        except (ValueError, TypeError):
            document = None
        if isinstance(document, dict):
            flags["rauthy_discovery_issuer"] = document.get("issuer") == ISSUER and not oidc[3]
    return {
        "scope": "exact public Dev GET only, no redirects, cookies, user credentials or admin APIs",
        "checks": flags,
        "statuses": {path: reading[0] for path, reading in readings.items()},
        "pass": all(flags.values()),
        "signed_human_user_or_project_authorization_proven": False,
        "native_password_form_visual_acceptance_proven": False,
    }


def main() -> int:
    result = review(get_statuses())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
