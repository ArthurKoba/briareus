#!/usr/bin/env python3
"""Read-only Rauthy release evidence, never a client/user provisioning tool.

Fixed Briareus Development public origin only; never requests credentials,
accepts arbitrary URLs, follows redirects, or prints provider cookies/tokens.
No privileged Rauthy REST operation, DB query, or login is performed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import ssl
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

PUBLIC_ORIGIN = "https://briareus.koba-nexus.ru"
ISSUER = PUBLIC_ORIGIN + "/auth/v1/"
DISCOVERY = ISSUER + ".well-known/openid-configuration"
AUTHORIZATION = ISSUER + "oidc/authorize"
TOKEN = ISSUER + "oidc/token"
JWKS = ISSUER + "oidc/certs"
MAX_BYTES = 131_072
TIMEOUT = 8
COMPOSE_DIR = Path(__file__).resolve().parent
SECURE_FLAGS = (
    "OPEN_USER_REG",
    "USER_REG_OPEN_REDIRECT",
    "ENABLE_DYN_CLIENT_REG",
    "ENABLE_EPHEMERAL_CLIENTS",
)
PRIVATE_JWK_FIELDS = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth", "k"})


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        _request: Request,
        _fp: object,
        _code: int,
        _msg: str,
        _headers: object,
        _new_url: str,
    ) -> None:
        return None


def _source_checks() -> dict[str, object]:
    """Check only exact tracked Compose security and persistence constraints."""
    results: dict[str, object] = {}
    for filename in ("docker-compose.yaml", "docker-compose.coolify.yaml"):
        text = (COMPOSE_DIR / filename).read_text()
        fields = {}
        for flag in SECURE_FLAGS:
            occurrences = re.findall(r"^\s+" + flag + r':\s*"([^"]+)"\s*$', text, re.M)
            fields[flag] = occurrences == ["false"]
        results[filename + ".enrollment_disabled"] = all(fields.values())
        results[filename + ".security_fields"] = fields
        results[filename + ".private_vendor_network"] = (
            "name: briareus-net" in text and "ports:" not in text
        )
    portable = (COMPOSE_DIR / "docker-compose.yaml").read_text()
    valkey_source = portable.partition("  briareus-valkey:")[2].partition("  briareus-rauthy:")[0]
    # Native Init and its single-use PoW reservation are separate TTL keys.
    # Evicting only the reservation permits a second issuance on live Init.
    results["valkey_auth_reservations_not_evicted"] = re.findall(
        r"maxmemory-policy ([a-z-]+)\\n", valkey_source
    ) == ["noeviction"]
    # PostgreSQL vendor readiness is scoped to Rauthy's own database; a
    # different owner DB failure must not block the existing identity provider.
    entrypoint = (COMPOSE_DIR / "postgres-entrypoint.sh").read_text()
    provider_health = (COMPOSE_DIR / "provider-db-health.sh").read_text()
    postgres_image = (COMPOSE_DIR / "Dockerfile").read_text()
    ignored_inputs = (COMPOSE_DIR / "Dockerfile.dockerignore").read_text().splitlines()
    # The restrictive Docker build context must include EVERY file copied by
    # the new image; Compose syntax/static health checks alone miss this.
    postgres_copy_inputs = (
        "postgres-entrypoint.sh",
        "provider-db-health.sh",
        "owner-bootstrap.psql",
        "owner-readiness.psql",
    )
    results["postgres_image_sources_in_build_context"] = all(
        f"!services/external/{filename}" in ignored_inputs
        and f"COPY services/external/{filename} " in postgres_image
        for filename in postgres_copy_inputs
    )
    results["rauthy_waits_for_provider_db_prerequisite"] = (
        'test: ["CMD", "/usr/local/bin/briareus-provider-db-health"]' in portable
        and "condition: service_healthy" in portable
        and "provider_ready_file=/run/briareus-rauthy-db-ready" in entrypoint
        and "pg_get_userbyid(datdba) = current_user" in entrypoint
        and 'if [ "$provider_owned" = t ]; then' in entrypoint
        and "COPY services/external/provider-db-health.sh" in postgres_image
    )
    # A marker created at process startup cannot protect a later provider
    # restart if its DB vanished or ownership changed while PG stays alive.
    results["provider_db_health_checks_current_catalog"] = (
        "test -f /run/briareus-rauthy-db-ready" in provider_health
        and "pg_isready -h 127.0.0.1 -p 5432" in provider_health
        and "PGPASSWORD" in provider_health
        and "-w -v ON_ERROR_STOP=1" in provider_health
        and "count(*) = 1 AND bool_and(pg_get_userbyid(datdba) = current_user)" in provider_health
        and "FROM pg_database WHERE datname = 'briareus_rauthy'" in provider_health
        and '[ "$provider_owned" = t ]' in provider_health
    )
    results["owner_db_reconciliation_not_provider_health_gate"] = (
        "owner_ready_file=/run/briareus-owner-databases-ready" in entrypoint
        and "briareus-owner-databases-ready" not in provider_health
        and 'if [ "$owners_reconciled" = true ]; then' in entrypoint
    )
    results["compose_dns_preserved"] = all(
        alias in portable
        for alias in (
            'aliases: ["briareus-postgres"]',
            'aliases: ["briareus-valkey"]',
            'aliases: ["briareus-rauthy"]',
        )
    )
    results["compose_vendor_volumes_declared"] = all(
        volume in portable
        for volume in (
            "postgres-data:/var/lib/postgresql",
            "valkey-data:/data",
            "rauthy-data:/app/data",
        )
    )
    # Greenfield identity retirement must never erase or recreate the
    # upstream Rauthy provider state. Verify only committed source, no SQL.
    inventory = json.loads((COMPOSE_DIR / "config/owner-databases.json").read_text())
    active = {item["database"] for item in inventory["initial"]}
    protected = set(inventory["protected_provider_databases"])
    legacy = set(inventory["excluded_legacy_databases_do_not_touch_automatically"])
    bootstrap = (COMPOSE_DIR / "owner-bootstrap.psql").read_text()
    results["active_database_inventory"] = active == {
        "briareus_access",
        "briareus_platform",
        "briareus_resources",
        "briareus_rauthy",
    }
    results["provider_db_protected"] = protected == {"briareus_rauthy"}
    # Legacy names appear in the *guard* only as existing-cluster evidence;
    # they must never be in the CREATE DATABASE generator's wanted list.
    database_create_source = bootstrap.partition("SELECT format(")[2].partition("\\gexec")[0]
    # Preserve safe replay after a partial first installation without
    # weakening the earlier lost-provider guard for populated clusters.
    results["fresh_bootstrap_provider_created_first"] = (
        "ORDER BY (wanted.dbname = 'briareus_rauthy') DESC, wanted.dbname" in database_create_source
    )
    results["legacy_db_not_provisioned"] = (
        legacy == {"briareus_identity", "briareus_dev"}
        and "briareus_identity" not in database_create_source
        and "briareus_dev" not in database_create_source
        and bool(database_create_source)
    )
    # The guard precedes every CREATE DATABASE; old platform/access/legacy
    # databases with a missing provider must fail without creating a blank IdP.
    guard_source = bootstrap.partition("\\gset")[0]
    guarded_non_provider = (
        "briareus_access",
        "briareus_platform",
        "briareus_resources",
        "briareus_files",
        "briareus_runtime",
        "briareus_reverse",
        "briareus_ingest",
        "briareus_identity",
        "briareus_dev",
    )
    results["missing_rauthy_db_fails_closed"] = (
        "EXISTS (SELECT 1 FROM pg_database WHERE datname = 'briareus_rauthy')" in guard_source
        and "OR NOT EXISTS (" in guard_source
        and all("'" + db + "'" in guard_source for db in guarded_non_provider)
        and "AS provider_bootstrap_safe" in guard_source
        and "\\if :provider_bootstrap_safe" in bootstrap
        and "\\else" in bootstrap
        and "protected Rauthy database missing on existing cluster" in bootstrap
        and bootstrap.index("\\gset") < bootstrap.index("\\gexec")
    )
    results["non_destructive_postgres_bootstrap"] = (
        "count(*) = 4" in bootstrap
        and "briareus_rauthy" in bootstrap
        and "DROP DATABASE" not in bootstrap.upper()
        and "TRUNCATE" not in bootstrap.upper()
        and "CREATE DATABASE" in bootstrap
    )
    # Operator preflight is an explicit-name catalog SELECT only, not a
    # programmable SQL reset or an inspection of sensitive Users tables.
    preflight_lines = (COMPOSE_DIR / "owner-readiness.psql").read_text().splitlines()
    statements = "\n".join(
        line
        for line in preflight_lines
        if not line.lstrip().startswith("--") and not line.lstrip().startswith("\\")
    )
    blocked_sql = re.search(
        r"\b(DROP|ALTER|CREATE|TRUNCATE|INSERT|UPDATE|DELETE|GRANT|"
        r"REVOKE|COPY|EXECUTE|VACUUM|CALL|DO)\b",
        statements,
        re.IGNORECASE,
    )
    expected_db_names = {
        "briareus_rauthy",
        "briareus_access",
        "briareus_platform",
        "briareus_resources",
        "briareus_files",
        "briareus_runtime",
        "briareus_reverse",
        "briareus_ingest",
        "briareus_identity",
        "briareus_dev",
    }
    results["preflight_is_catalog_select_only"] = (
        re.match(r"^SELECT\s+", statements.lstrip(), re.IGNORECASE) is not None
        and statements.count(";") == 1
        and blocked_sql is None
        and "FROM (VALUES" in statements
        and "pg_database" in statements
        and "pg_stat_database" in statements
        and all(statements.count("'" + db + "'") == 1 for db in expected_db_names)
    )
    for filename in ("docker-compose.yaml", "docker-compose.coolify.yaml"):
        text = (COMPOSE_DIR / filename).read_text()
        results[filename + ".canonical_bootstrap_db"] = (
            'POSTGRES_DB: "postgres"' in text and "briareus_dev" not in text
        )
    results["source_pass"] = all(
        value
        for key, value in results.items()
        if key != "source_pass" and not key.endswith(".security_fields")
    )
    return results


def _request(path: str) -> tuple[int, bytes]:
    """No redirects, bounded response; only paths under the constant origin."""
    url = PUBLIC_ORIGIN + path
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "briareus.koba-nexus.ru":
        raise ValueError("outside approved public provider")
    req = Request(
        url,
        headers={
            "Accept": "application/json, text/html",
            "User-Agent": "Briareus-ProviderContract/1",
        },
        method="GET",
    )
    # Shell proxy variables must not redirect this fixed-origin evidence path.
    opener = build_opener(
        ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=ssl.create_default_context())
    )
    try:
        with opener.open(req, timeout=TIMEOUT) as response:
            raw = response.read(MAX_BYTES + 1)
            status = response.status
    except HTTPError as exc:
        with exc:
            raw = exc.read(MAX_BYTES + 1)
        status = exc.code
    if len(raw) > MAX_BYTES:
        raise ValueError("provider response exceeds allowed size")
    return status, raw


def _public_checks() -> dict[str, object]:
    """Read-only public issuer/JWKS and private-route security, not browser login."""
    status, raw = _request("/auth/v1/.well-known/openid-configuration")
    result: dict[str, object] = {"discovery_status": status}
    if status != 200:
        result["public_pass"] = False
        return result
    doc = json.loads(raw)
    if not isinstance(doc, dict):
        raise ValueError("provider discovery must be a JSON object")
    response_types = doc.get("response_types_supported")
    challenge_methods = doc.get("code_challenge_methods_supported")
    result["discovery_contract"] = {
        "issuer": doc.get("issuer") == ISSUER,
        "authorize": doc.get("authorization_endpoint") == AUTHORIZATION,
        "token": doc.get("token_endpoint") == TOKEN,
        "jwks": doc.get("jwks_uri") == JWKS,
        "authorization_code": isinstance(response_types, list) and "code" in response_types,
        "pkce_s256": isinstance(challenge_methods, list) and "S256" in challenge_methods,
    }
    jwks_status, jwks_raw = _request("/auth/v1/oidc/certs")
    result["jwks_status"] = jwks_status
    if jwks_status == 200:
        jwks = json.loads(jwks_raw)
        if not isinstance(jwks, dict):
            raise ValueError("provider JWKS must be a JSON object")
        keys = jwks.get("keys", [])
        if not isinstance(keys, list) or not all(isinstance(key, dict) for key in keys):
            raise ValueError("provider JWKS keys must be an array of objects")
        result["jwks_public_keys"] = len(keys)
        result["jwks_no_private_fields"] = bool(keys) and all(
            not (PRIVATE_JWK_FIELDS & set(key))
            and isinstance(key.get("kid"), str)
            and bool(key["kid"])
            for key in keys
        )
        # Stable fingerprint of PUBLIC signing metadata; compare around releases.
        result["public_jwks_sha256"] = hashlib.sha256(
            json.dumps(keys, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    else:
        result["jwks_no_private_fields"] = False

    # Owner-native Control Panel never requires Rauthy-hosted HTML.
    # Do not initialize disposable hosted-login sessions from this probe.
    paths = {
        "admin": "/auth/v1/users",
        # Mixed upstream user/operator route. Native Panel reads through
        # its BFF, so public exposure is optional; anonymous success is not.
        "self_user_by_id": "/auth/v1/users/" + secrets.token_hex(12),
        "admin_attributes": "/auth/v1/users/attr",
        "admin_clients": "/auth/v1/clients",
        "registration_users": "/auth/v1/users/register",
        "registration_root": "/auth/v1/register",
    }
    with ThreadPoolExecutor(max_workers=len(paths)) as pool:
        responses = dict(zip(paths, pool.map(_request, paths.values()), strict=True))
    # Admin-only collection/configuration routes remain a private boundary.
    # Native Panel does not require public upstream self-profile routing.
    admin_keys = ("admin", "admin_attributes", "admin_clients")
    result["public_admin_probe_statuses"] = {key: responses[key][0] for key in admin_keys}
    # An upstream 401/403 still exposes private Rauthy management REST.
    # All probes must be rejected by the Gateway itself (404) before proxying.
    result["admin_route_privacy_accepted"] = all(responses[key][0] == 404 for key in admin_keys)
    # Either upstream authentication or a closed public route may reject
    # this anonymous request. Do not require hosted Rauthy account UI solely
    # to make the probe pass. Redirects, anonymous success and outages fail.
    result["self_user_by_id_without_session_status"] = responses["self_user_by_id"][0]
    result["self_user_route_unauthenticated_gate"] = responses["self_user_by_id"][0] in (
        401,
        403,
        404,
    )
    result["public_self_profile_required"] = False
    result["real_self_profile_login"] = "NOT_PROVEN_NO_USER_SESSION"
    # These are only representative GETs, not a complete registration audit.
    result["representative_registration_get_statuses"] = {
        paths[key]: responses[key][0] for key in ("registration_users", "registration_root")
    }
    result["signup_disabled_everywhere"] = "NOT_PROVEN_BY_PUBLIC_GET"
    result["valid_user_code_flow"] = "NOT_PROVEN_NO_USER_CREDENTIALS"
    result["resource_token_audience"] = "NOT_PROVEN_NO_SIGNED_MCP_TOKEN"
    # Product decision: the user's sign-in form lives inside Control Panel.
    # Public issuer/JWKS checks cannot prove registration or native login.
    result["registered_client_redirect"] = "NOT_PROVEN_NO_PRIVATE_CLIENT_PROOF"
    result["native_control_panel_login"] = "NOT_PROVEN_NO_NATIVE_BFF_CHALLENGE_FLOW"
    result["public_oidc_pass"] = (
        all(result["discovery_contract"].values())
        and jwks_status == 200
        and result["jwks_no_private_fields"]
    )
    result["public_pass"] = (
        result["public_oidc_pass"]
        and result["admin_route_privacy_accepted"]
        and result["self_user_route_unauthenticated_gate"]
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--public",
        action="store_true",
        help="also check fixed public HTTPS OIDC endpoints without credentials",
    )
    args = parser.parse_args()
    report = {"source": _source_checks()}
    if args.public:
        try:
            report["public"] = _public_checks()
        except (
            URLError,
            TimeoutError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            report["public"] = {"public_pass": False, "error_type": type(exc).__name__}
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return (
        0
        if (
            report["source"]["source_pass"]
            and (not args.public or report.get("public", {}).get("public_pass"))
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
