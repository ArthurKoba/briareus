"""Fast startup-import contract for the separate authorization service."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


class AuthorizationRuntimeImportTest(unittest.TestCase):
    def test_asgi_application_imports_without_external_services(self) -> None:
        private_key = ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env.update(
            PYTHONPATH=str(root / "services"),
            OTLP_ENDPOINT="",
            AUTHORIZATION_PUBLIC_BASE_URL="https://authorization.example.test",
            MCP_PUBLIC_BASE_URL="https://mcp.example.test",
            AUTHORIZATION_POSTGRES_USER="test_user",
            AUTHORIZATION_POSTGRES_PASSWORD="test_password",
            AUTHORIZATION_BOOTSTRAP_USERNAME="test_admin",
            AUTHORIZATION_BOOTSTRAP_PASSWORD="test_password",
            AUTHORIZATION_JWT_PRIVATE_KEY_PEM=private_key,
            AUTHORIZATION_GATEWAY_SERVICE_TOKEN="test_gateway_token",
            AUTHORIZATION_ADMIN_SERVICE_TOKEN="test_admin_token",
        )
        result = subprocess.run(
            [sys.executable, "-c", "from authorization.runtime import app; assert app.routes"],
            env=env,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2500:])
