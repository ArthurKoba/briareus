from __future__ import annotations

import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from authorization.security import (
    hash_password,
    issue_access_token,
    verify_access_token,
    verify_password,
)


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
            kid="test-key",
            issuer="https://mcp.example.test",
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
            issuer="https://mcp.example.test",
            audience="https://mcp.example.test/github/mcp",
        )
        self.assertIsNotNone(valid)
        self.assertEqual(valid["sub"], "user-1")
        self.assertEqual(valid["session_id"], "oauth-session-1")

        wrong_resource = verify_access_token(
            token,
            public_key=private_key.public_key(),
            issuer="https://mcp.example.test",
            audience="https://mcp.example.test/terminal/mcp",
        )
        self.assertIsNone(wrong_resource)

    def test_key_round_trip_is_p256(self) -> None:
        private_key = ec.generate_private_key(ec.SECP256R1())
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        self.assertIn(b"BEGIN PRIVATE KEY", pem)


if __name__ == "__main__":
    unittest.main()
