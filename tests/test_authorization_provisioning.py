"""The shared PostgreSQL role must never be altered by Auth provisioning."""

import os
import unittest
from unittest.mock import AsyncMock, patch

from scripts.provision_authorization_database import _ensure_database, main


class AuthorizationProvisioningTests(unittest.IsolatedAsyncioTestCase):
    async def test_reusing_shared_role_preserves_existing_database_owner(self) -> None:
        connection = AsyncMock()
        connection.fetchval.side_effect = ['"authorization"', '"postgres"', 1]

        await _ensure_database(
            connection,
            database="authorization",
            owner="postgres",
            preserve_existing=True,
        )

        connection.execute.assert_not_called()

    async def test_provisioner_refuses_to_alter_existing_cluster_role(self) -> None:
        values = {
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "dummy-only",
            "AUTHORIZATION_POSTGRES_USER": "postgres",
            "AUTHORIZATION_POSTGRES_PASSWORD": "dummy-only",
        }
        with (
            patch.dict(os.environ, values, clear=True),
            self.assertRaisesRegex(RuntimeError, "refusing to change"),
        ):
            await main()
