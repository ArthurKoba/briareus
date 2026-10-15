"""Pure-data tests; no network or secrets required."""
import importlib.util
from pathlib import Path
import sys
import unittest

_source=Path(__file__).with_name("local-stack-readiness.py")
_spec=importlib.util.spec_from_file_location("local_stack_readiness", _source)
_module=importlib.util.module_from_spec(_spec)
sys.modules[_spec.name]=_module
_spec.loader.exec_module(_module)


class OidcReadinessSourceTests(unittest.TestCase):
    def test_source_config_is_exact(self):
        self.assertTrue(_module.valid_oidc_public_config(dict(_module.EXPECTED_OIDC_DEV), profile="dev"))

    def test_local_sandbox_requires_explicit_profile(self):
        local=dict(_module.EXPECTED_OIDC_LOCAL)
        self.assertFalse(_module.valid_oidc_public_config(local))
        self.assertTrue(_module.valid_oidc_public_config(local,profile="local-sandbox"))
        self.assertFalse(_module.valid_oidc_public_config(dict(_module.EXPECTED_OIDC_DEV),profile="local-sandbox"))

    def test_local_sandbox_cannot_impersonate_a_different_endpoint(self):
        local=dict(_module.EXPECTED_OIDC_LOCAL)
        local["jwks_uri"]="https://localhost:18445/auth/v1/oidc/certs"
        self.assertFalse(_module.valid_oidc_public_config(local,profile="local-sandbox"))

    def test_no_other_issuer(self):
        value=dict(_module.EXPECTED_OIDC_DEV)
        value["issuer"]="https://localhost:18444/auth/v1/"
        self.assertFalse(_module.valid_oidc_public_config(value))

    def test_no_wrong_client(self):
        value=dict(_module.EXPECTED_OIDC_DEV)
        value["client_id"]="briareus-local-panel"
        self.assertFalse(_module.valid_oidc_public_config(value))

    def test_no_wrong_userinfo(self):
        value=dict(_module.EXPECTED_OIDC_DEV)
        value["userinfo_endpoint"]="https://untrusted.invalid/userinfo"
        self.assertFalse(_module.valid_oidc_public_config(value))

    def test_no_extra_sensitive_keys(self):
        value=dict(_module.EXPECTED_OIDC_DEV)
        value["client_secret"]="unexpected"
        self.assertFalse(_module.valid_oidc_public_config(value))

    def test_no_tokens_in_endpoint_urls(self):
        value=dict(_module.EXPECTED_OIDC_DEV)
        value["token_endpoint"]+="?key=secret"
        self.assertFalse(_module.valid_oidc_public_config(value))

    def test_no_missing_metadata(self):
        value=dict(_module.EXPECTED_OIDC_DEV)
        del value["jwks_uri"]
        self.assertFalse(_module.valid_oidc_public_config(value))

    def test_no_untrusted_loopback_endpoints(self):
        value=dict(_module.EXPECTED_OIDC_DEV)
        value["authorization_endpoint"]="http://127.0.0.1:18444/auth/v1/oidc/authorize"
        self.assertFalse(_module.valid_oidc_public_config(value))


if __name__ == "__main__":
    unittest.main()
