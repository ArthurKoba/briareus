"""Keep Coolify parser-discovered env keys consistent with portable Auth."""

import unittest
from pathlib import Path

import yaml


class AuthorizationDeploymentComposeTests(unittest.TestCase):
    def test_coolify_adapter_exposes_all_portable_environment_inputs(self) -> None:
        directory = Path(__file__).resolve().parents[1] / "services" / "authorization"
        portable = yaml.safe_load((directory / "docker-compose.yaml").read_text())
        coolify = yaml.safe_load((directory / "docker-compose.coolify.yaml").read_text())

        base_service = portable["services"]["authorization"]
        adapter = coolify["services"]["authorization"]
        self.assertEqual(
            adapter["extends"],
            {"file": "docker-compose.yaml", "service": "authorization"},
        )
        env = dict(adapter["environment"])
        self.assertEqual(env.pop("SERVICE_URL_AUTHORIZATION_8000"), "/")
        portable_env = dict(base_service["environment"])
        self.assertEqual(set(env), set(portable_env))
        self.assertEqual(
            portable_env.pop("AUTHORIZATION_PUBLIC_BASE_URL"),
            "${AUTHORIZATION_PUBLIC_BASE_URL:-}",
        )
        self.assertEqual(
            env.pop("AUTHORIZATION_PUBLIC_BASE_URL"),
            "${AUTHORIZATION_PUBLIC_BASE_URL:-${SERVICE_URL_AUTHORIZATION}}",
        )
        self.assertEqual(env, portable_env)
        for key in (
            "MCP_PUBLIC_BASE_URL",
            "AUTHORIZATION_BOOTSTRAP_USERNAME",
            "AUTHORIZATION_BOOTSTRAP_PASSWORD",
            "AUTHORIZATION_JWT_PRIVATE_KEY_PEM",
            "AUTHORIZATION_GATEWAY_SERVICE_TOKEN",
            "AUTHORIZATION_ADMIN_SERVICE_TOKEN",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
        ):
            self.assertEqual(env[key], f"${{{key}:?}}")
        self.assertEqual(env["POSTGRES_DB"], "${POSTGRES_DB:-authorization}")
        self.assertEqual(coolify["networks"]["mcp"], {"external": True, "name": "mcp"})
        self.assertEqual(adapter["networks"], ["mcp"])
