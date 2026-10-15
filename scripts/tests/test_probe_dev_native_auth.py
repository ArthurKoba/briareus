"""Offline public Dev readiness verdict; no network, cookies or credentials."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "probe_dev_native_auth.py"
SPEC = importlib.util.spec_from_file_location("published_native_public_probe", SOURCE)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def fixture() -> dict[str, m.PublicProbe]:
    cases = {
        p: m.PublicProbe(404, "application/json", b"{}", False, "no-store", "", False)
        for p in m.PATHS
    }
    cases["/panel/"] = m.PublicProbe(200, "text/html", b"<html></html>", False, "", "", False)
    cases["/api/v1/auth/capabilities"] = m.PublicProbe(
        200,
        "application/json",
        json.dumps(
            {
                "protocol": "rauthy-native-v1",
                "first_factor": "password",
                "pow": "client-solved",
                "cancel": True,
                "continuations": [],
            }
        ).encode(),
        False,
        "no-store",
        "no-cache",
        False,
    )
    cases["/api/v1/auth/session"] = m.PublicProbe(
        401,
        "application/json",
        b'{"error":{"code":"OIDC_SESSION_REQUIRED"}}',
        False,
        "no-store",
        "no-cache",
        False,
    )
    cases["/auth/v1/.well-known/openid-configuration"] = m.PublicProbe(
        200,
        "application/json",
        json.dumps({"issuer": m.ISSUER}).encode(),
        False,
        "no-store",
        "",
        False,
    )
    return cases


class PublicDevAuthReadinessTests(unittest.TestCase):
    def test_positive_route_security_is_not_real_user_login(self) -> None:
        report = m.review(fixture())
        self.assertTrue(report["pass"])
        self.assertEqual(len(report["checks"]), 6)
        self.assertFalse(report["signed_human_user_or_project_authorization_proven"])
        self.assertFalse(report["native_password_form_visual_acceptance_proven"])

    def test_old_text_anonymous_401_is_not_accepted(self) -> None:
        values = fixture()
        values["/api/v1/auth/session"] = values["/api/v1/auth/session"]._replace(
            body=b'{"detail":"OIDC browser session required"}'
        )
        self.assertFalse(m.review(values)["checks"]["anonymous_session_denied_without_cache"])

    def test_missing_no_store_or_pragma_fails(self) -> None:
        for field in ("cache_control", "pragma"):
            values = fixture()
            values["/api/v1/auth/session"] = values["/api/v1/auth/session"]._replace(**{field: ""})
            self.assertFalse(m.review(values)["pass"])

    def test_browser_cookie_on_anonymous_or_redirect_fails(self) -> None:
        for change in ({"sets_cookie": True}, {"redirected": True}, {"status": 302}):
            values = fixture()
            values["/api/v1/auth/session"] = values["/api/v1/auth/session"]._replace(**change)
            self.assertFalse(m.review(values)["checks"]["anonymous_session_denied_without_cache"])

    def test_each_admin_rest_path_must_be_gateway_404(self) -> None:
        for path in ("/auth/v1/users", "/auth/v1/users/attr", "/auth/v1/clients"):
            values = fixture()
            values[path] = values[path]._replace(status=401)
            self.assertFalse(m.review(values)["checks"]["provider_admin_routes_private"])

    def test_obsolete_native_return_and_oidc_realm_fail(self) -> None:
        values = fixture()
        values["/api/auth/native/capabilities"] = values["/api/auth/native/capabilities"]._replace(
            status=200
        )
        self.assertFalse(m.review(values)["checks"]["obsolete_native_route_closed"])
        values = fixture()
        values["/auth/v1/.well-known/openid-configuration"] = values[
            "/auth/v1/.well-known/openid-configuration"
        ]._replace(body=b'{"issuer":"https://foreign.invalid/auth/v1/"}')
        self.assertFalse(m.review(values)["checks"]["rauthy_discovery_issuer"])

    def test_missing_route_or_oversized_signed_dto_fail(self) -> None:
        values = fixture()
        del values["/auth/v1/clients"]
        with self.assertRaises(ValueError):
            m.review(values)
        values = fixture()
        values["/api/v1/auth/capabilities"] = values["/api/v1/auth/capabilities"]._replace(
            body=b"x" * (m.MAX_BYTES + 1)
        )
        self.assertFalse(m.review(values)["checks"]["native_v1_capabilities"])


if __name__ == "__main__":
    unittest.main()
