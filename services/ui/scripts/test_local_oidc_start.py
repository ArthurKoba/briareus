"""Structural source-only OIDC start tests; no network or credential usage."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import unittest
from urllib.parse import urlencode


def load(name: str, filename: str):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


s=load("local_oidc_start","local-oidc-start.py")
params={
 "response_type":"code","client_id":"briareus-local-panel",
 "redirect_uri":"https://briareus.koba-nexus.ru/api/auth/oidc/callback",
 "scope":"openid profile","state":"a"*48,"nonce":"b"*48,
 "code_challenge":"c"*43,"code_challenge_method":"S256",
}
location="https://localhost:18444/auth/v1/oidc/authorize?"+urlencode(params)
cookie="__Host-briareus_oidc_transaction="+("a"*48)+"; Path=/; Max-Age=300; Secure; HttpOnly; SameSite=lax"


class OidcStartStructuralTests(unittest.TestCase):
    def test_actual_local_shape_still_blocks_public_dev_callback(self):
        checks=s.validate_start_headers(302,location,[cookie])
        self.assertEqual(checks,{
            "bff_start_302":True,
            "provider_authorize_pinned":True,
            "s256_state_nonce_scope":True,
            "host_only_transaction_cookie":True,
            "isolated_callback_accepted":False,
        })

    def test_wrong_provider_does_not_pass(self):
        self.assertFalse(s.validate_start_headers(302,location.replace("localhost:18444","untrusted.invalid"),[cookie])["provider_authorize_pinned"])

    def test_weak_pkce_and_no_state_denied(self):
        for variant in ("plain","S128"):
            bad={**params,"code_challenge_method":variant}
            url="https://localhost:18444/auth/v1/oidc/authorize?"+urlencode(bad)
            self.assertFalse(s.validate_start_headers(302,url,[cookie])["s256_state_nonce_scope"])
        bad={**params,"state":"short"}
        url="https://localhost:18444/auth/v1/oidc/authorize?"+urlencode(bad)
        self.assertFalse(s.validate_start_headers(302,url,[cookie])["s256_state_nonce_scope"])

    def test_nonce_and_state_must_be_independent(self):
        bad={**params,"nonce":params["state"]}
        uri="https://localhost:18444/auth/v1/oidc/authorize?"+urlencode(bad)
        self.assertFalse(s.validate_start_headers(302,uri,[cookie])["s256_state_nonce_scope"])

    def test_invalid_port_does_not_crash(self):
        uri=location.replace("localhost:18444","localhost:notaport")
        self.assertFalse(all(s.validate_start_headers(302,uri,[cookie]).values()))

    def test_unknown_injected_query_and_duplicate_fields_block(self):
        self.assertFalse(s.validate_start_headers(302,location+"&access_token=leak",[cookie])["s256_state_nonce_scope"])
        self.assertFalse(s.validate_start_headers(302,location+"&state=attacker",[cookie])["s256_state_nonce_scope"])

    def test_transaction_cookie_must_be_strict_host_only(self):
        for variant in [
            cookie.replace("Secure; ",""),
            cookie.replace("HttpOnly; ",""),
            cookie.replace("SameSite=lax","SameSite=None"),
            cookie+"; Domain=example.invalid",
            "briareus_oidc_transaction="+cookie.split("=",1)[1],
        ]:
            self.assertFalse(s.validate_start_headers(302,location,[variant])["host_only_transaction_cookie"])

    def test_transaction_cookie_binds_exact_state_and_ttl(self):
        wrong_state = cookie.replace("a"*48,"z"*48)
        self.assertFalse(s.validate_start_headers(302,location,[wrong_state])["host_only_transaction_cookie"])
        too_long = cookie.replace("Max-Age=300","Max-Age=901")
        self.assertFalse(s.validate_start_headers(302,location,[too_long])["host_only_transaction_cookie"])
        no_ttl = cookie.replace("Max-Age=300; ","")
        self.assertFalse(s.validate_start_headers(302,location,[no_ttl])["host_only_transaction_cookie"])

    def test_backend_approved_local_tls_callback_is_exclusively_pinned(self):
        params_isolated={**params,"redirect_uri":"https://127.0.0.1:18446/api/auth/oidc/callback"}
        url="https://localhost:18444/auth/v1/oidc/authorize?"+urlencode(params_isolated)
        validated=s.validate_start_headers(302,url,[cookie])
        self.assertTrue(all(validated.values()))
        wrong={**params_isolated,"redirect_uri":"https://localhost:18446/api/auth/oidc/callback"}
        wrong_url="https://localhost:18444/auth/v1/oidc/authorize?"+urlencode(wrong)
        self.assertFalse(s.validate_start_headers(
            302,wrong_url,[cookie]
        )["isolated_callback_accepted"])

    def test_no_untrusted_expanded_loopback_port(self):
        params_bad={**params,"redirect_uri":"https://127.0.0.1:18447/api/auth/oidc/callback"}
        url="https://localhost:18444/auth/v1/oidc/authorize?"+urlencode(params_bad)
        self.assertFalse(s.validate_start_headers(302,url,[cookie])["isolated_callback_accepted"])

    def test_callback_is_never_accepted_by_hardcoding_public_dev(self):
        self.assertFalse(s.validate_start_headers(302,location,[cookie])["isolated_callback_accepted"])

    def test_status_must_be_exactly_302(self):
        self.assertFalse(s.validate_start_headers(200,location,[cookie])["bff_start_302"])
        self.assertFalse(s.validate_start_headers(307,location,[cookie])["bff_start_302"])

    def test_approved_callback_still_needs_actual_tls_listener(self):
        approved={key:True for key in (
            "bff_start_302","provider_authorize_pinned",
            "s256_state_nonce_scope","host_only_transaction_cookie",
            "isolated_callback_accepted",
        )}
        stage, ready=s.classify_start(302,approved,check_provider=False)
        self.assertEqual(stage,"isolated_listener_not_checked")
        self.assertFalse(ready)
        approved.update({"provider_authorize_entry_200":True,
                         "isolated_tls_ui_200":False,
                         "isolated_bff_anonymous_401":True})
        stage, ready=s.classify_start(302,approved,check_provider=True)
        self.assertEqual(stage,"isolated_listener_unavailable")
        self.assertFalse(ready)
        approved["isolated_tls_ui_200"]=True
        stage, ready=s.classify_start(302,approved,check_provider=True)
        self.assertEqual(stage,"accepted")
        self.assertTrue(ready)

    def test_unisolated_callback_cannot_gain_readiness_from_html200(self):
        evidence={key:True for key in (
            "bff_start_302","provider_authorize_pinned",
            "s256_state_nonce_scope","host_only_transaction_cookie",
            "provider_authorize_entry_200",
        )}
        evidence.update({"isolated_callback_accepted":False,
                        "isolated_tls_ui_200":True,"isolated_bff_anonymous_401":True})
        stage, ready=s.classify_start(302,evidence,check_provider=True)
        self.assertEqual(stage,"callback_not_isolated")
        self.assertFalse(ready)

    def test_no_location_or_missing_transaction_never_passes(self):
        checks=s.validate_start_headers(302,"",[])
        self.assertFalse(all(checks.values()))


if __name__=="__main__":
    unittest.main()
