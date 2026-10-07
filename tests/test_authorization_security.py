from __future__ import annotations

import base64
import unittest

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from authorization.security import (
    hash_password,
    issue_access_token,
    load_signing_key,
    public_jwk,
    signing_key_id,
    verify_access_token,
    verify_password,
)
from bridge.authorization_client import AuthorizationJwksClient, LocalAuthorizationTokenVerifier
from common.settings import GatewayAuthorizationSettings


def signing_key_value(private_key: ec.EllipticCurvePrivateKey) -> str:
    der = private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return base64.b64encode(der).decode()


class AuthorizationSecurityTest(unittest.TestCase):
    def test_password_hash_uses_argon2id_and_verifies(self) -> None:
        encoded = hash_password("correct horse battery staple")
        self.assertTrue(encoded.startswith("$argon2id$"))
        self.assertTrue(verify_password("correct horse battery staple", encoded))
        self.assertFalse(verify_password("wrong", encoded))

    def test_access_token_is_bound_to_exact_audience(self) -> None:
        private_key = ec.generate_private_key(ec.SECP256R1())
        token, _ = issue_access_token(
            private_key=private_key,
            kid=signing_key_id(private_key.public_key()),
            issuer="https://authorization.example.test",
            audience="https://mcp.example.test/github/mcp",
            subject="user-1",
            username="admin",
            client_id="client-1",
            scopes=["read:user"],
            session_id="oauth-session-1",
            ttl_seconds=300,
        )

        valid = verify_access_token(
            token,
            public_key=private_key.public_key(),
            issuer="https://authorization.example.test",
            audience="https://mcp.example.test/github/mcp",
        )
        self.assertIsNotNone(valid)
        assert valid is not None
        self.assertEqual(valid["sub"], "user-1")
        self.assertEqual(valid["session_id"], "oauth-session-1")

        wrong_resource = verify_access_token(
            token,
            public_key=private_key.public_key(),
            issuer="https://authorization.example.test",
            audience="https://mcp.example.test/terminal/mcp",
        )
        self.assertIsNone(wrong_resource)

    def test_single_line_signing_key_round_trip_and_derived_kid(self) -> None:
        private_key = ec.generate_private_key(ec.SECP256R1())
        encoded = signing_key_value(private_key)
        self.assertNotIn("\n", encoded)
        loaded = load_signing_key(encoded)
        expected_kid = signing_key_id(private_key.public_key())
        self.assertEqual(signing_key_id(loaded.public_key()), expected_kid)
        self.assertEqual(public_jwk(loaded.public_key())["kid"], expected_kid)


class GatewayAuthorizationVerifierTest(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_fetches_jwks_and_verifies_mcp_audience(self) -> None:
        private_key = ec.generate_private_key(ec.SECP256R1())
        jwk = public_jwk(private_key.public_key())
        settings = GatewayAuthorizationSettings.model_construct(
            enabled=True,
            public_base_url="https://authorization.example.test",
            mcp_public_base_url="https://mcp.example.test",
            authorization_internal_url="http://authorization:8000",
        )

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/.well-known/jwks.json")
            return httpx.Response(200, json={"keys": [jwk]})

        resource = "https://mcp.example.test/github/mcp"
        token, _ = issue_access_token(
            private_key=private_key,
            kid=jwk["kid"],
            issuer="https://authorization.example.test",
            audience=resource,
            subject="user-1",
            username="admin",
            client_id="client-1",
            scopes=["read:user"],
            session_id="oauth-session-1",
            ttl_seconds=300,
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://authorization:8000",
        ) as client:
            jwks = AuthorizationJwksClient(settings, client=client)
            verifier = LocalAuthorizationTokenVerifier(settings, resource, jwks)
            verified = await verifier.verify_token(token)
        self.assertIsNotNone(verified)


if __name__ == "__main__":
    unittest.main()
