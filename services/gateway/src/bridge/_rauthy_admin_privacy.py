"""Source-verified Rauthy v0.37.1 public Admin REST privacy slices.

Provider login, OAuth/OIDC, recovery and user self-service remain upstream.
Only independently confirmed privileged handler routes are filtered here;
the Panel BFF uses separate private Rauthy provider transport.
Source: upstream sebadob/rauthy tag v0.37.1 src/api/src/*.rs.
"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import unquote

RouteDisposition = Literal["forward", "bad_path", "private_admin"]
_BAD_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")
_FORBIDDEN_ESCAPE = ("%25", "%2f", "%5c", "%00")
_ADMIN_ONLY_NAMESPACES = frozenset(
    {
        "admin",
        "api_keys",
        "backup",
        "blacklist",
        "email",
        "events",
        "groups",
        "roles",
        "scopes",
        "sessions",
    }
)
_ADMIN_PROVIDER_ROUTES = frozenset({"create", "lookup"})
_ADMIN_SINGLE_ROUTES = frozenset(
    {"auth_check_admin", "search", "login_time", "password_hash_times"}
)


def classify_rauthy_public_path(path: str, method: str) -> RouteDisposition:
    """Deny source-proven admin methods; leave login and self-service intact.

    Namespace-wide denies apply only where the v0.37.1 Rust handlers
    require a privileged Admin/Group-Admin principal for every endpoint.
    Mixed namespaces such as clients/providers/kv get method-aware rules.
    """
    if _BAD_ESCAPE.search(path) or any(encoded in path.casefold() for encoded in _FORBIDDEN_ESCAPE):
        return "bad_path"
    canonical = unquote(path)
    if (
        "�" in canonical
        or "//" in canonical
        or any(segment in {".", ".."} for segment in canonical.split("/"))
    ):
        return "bad_path"
    parts = canonical.rstrip("/").casefold().split("/")
    if parts[:3] != ["", "auth", "v1"] or len(parts) < 4:
        return "forward"
    root, remaining = parts[3], parts[4:]
    method = method.upper()

    if root in _ADMIN_ONLY_NAMESPACES:
        # These are privileged REST management routes or the Admin HTML
        # interface. The HTML handlers may render without a direct
        # principal check, which is WHY public routing must exclude them.
        return "private_admin"

    if root == "users":
        if not remaining:
            # The collection GET/POST is Admin/Group-Admin, not registration.
            return "private_admin"
        if remaining[0] in {"attr", "email"}:
            # Custom attribute schema and arbitrary e-mail lookup are Admin.
            return "private_admin"
        if len(remaining) == 1 and method in {"PUT", "PATCH", "DELETE"}:
            # Direct user mutation; self-service has /users/{id}/self.
            return "private_admin"

    if root == "clients":
        if not remaining:
            # Admin client list/create; Dynamic Client Registration has
            # its own separate /clients_dyn namespace.
            return "private_admin"
        if remaining == ["validate_uri"]:
            # Login/registration/password-reset redirect validation.
            return "forward" if method == "POST" else "private_admin"
        if len(remaining) == 1 and method in {"GET", "PUT", "DELETE"}:
            return "private_admin"
        if len(remaining) == 2:
            if remaining[1] == "secret":
                return "private_admin"
            if remaining[1] in {"logo", "favicon"} and method != "GET":
                # Branding GET must remain available to OIDC login pages.
                return "private_admin"
        # /clients/{id}/forward_auth and callback remain public.

    if root == "providers":
        if not remaining:
            # POST /providers returns privileged provider configuration.
            return "private_admin"
        if remaining[0] in _ADMIN_PROVIDER_ROUTES:
            return "private_admin"
        if len(remaining) == 1 and method in {"PUT", "DELETE"}:
            # Auth-provider update/delete; /providers/link uses DELETE
            # for the current user's session and is an exception.
            return "forward" if remaining[0] == "link" else "private_admin"
        if len(remaining) == 2:
            if remaining[1] == "delete_safe":
                return "private_admin"
            if remaining[1] == "img" and method != "GET":
                return "private_admin"
        # /providers/minimal, login, callback, link and image GET remain.

    if root == "kv" and remaining and remaining[0] == "ns":
        # KV namespace administration is Admin-session only; the
        # separately scoped public/Access-Key KV APIs must still route.
        return "private_admin"

    if root == "oidc" and remaining == ["rotate_jwk"] and method == "POST":
        # Signing key rotation is Rauthy Secrets.Update, not an OAuth
        # protocol flow. OIDC login/logout/session/token/JWKS remain public.
        return "private_admin"

    if root == "theme" and method != "GET":
        # Client and login-page theme CSS must remain readable, but only
        # Admin/API clients may upload, update or delete theme resources.
        return "private_admin"

    if root == "tos":
        if not remaining or remaining[0] == "user":
            # Admin ToS creation/list and another user's acceptance state.
            return "private_admin"
        # /tos/latest, /tos/accept, /tos/deny belong to hosted login.
        return "forward"

    if root == "pam" and remaining:
        section = remaining[0]
        if section == "emails_unlinked" or section == "groups":
            return "private_admin"
        if section == "hosts":
            if len(remaining) == 1:
                return "private_admin"
            if remaining[1] == "user_access":
                # Authenticated User's own host access is not Admin.
                return "forward"
            if len(remaining) == 2 and method in {"GET", "PUT", "DELETE"}:
                return "private_admin"
            if len(remaining) >= 3 and remaining[2] == "secret":
                return "private_admin"
            # /pam/hosts/{id}/whoami is host-scoped; keep provider auth.
        if section == "users":
            if len(remaining) == 1:
                return "private_admin"
            if remaining[1] in {"self", "authorized_keys"}:
                # User's own key administration and host-key lookup.
                return "forward"
            if len(remaining) == 2 and method in {"GET", "PUT", "DELETE"}:
                return "private_admin"
            if len(remaining) >= 3 and remaining[2] == "authorized_key":
                return "private_admin"
        # /pam/login, /pam/mfa, /pam/password, /pam/preflight,
        # /pam/getent and /pam/validate remain provider-owned auth.

    if root in _ADMIN_SINGLE_ROUTES:
        return "private_admin"
    if root == "encryption" and remaining and remaining[0] in {"keys", "migrate"}:
        return "private_admin"
    if root == "password_policy" and method != "GET":
        # Authenticated User GET is self-service, privileged PUT is Admin.
        return "private_admin"

    return "forward"
