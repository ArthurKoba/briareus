"""Fail-closed, no-network invariants of the Dev owner read-only inventory."""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "dev_owner_db_readonly_inventory.py"
SPEC = importlib.util.spec_from_file_location("dev_owner_inventory_test_target", SRC)
assert SPEC is not None and SPEC.loader is not None
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


def _fixture(owner: str = "platform") -> dict[str, str]:
    return {
        "POSTGRES_HOST": "briareus-postgres",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": inventory._OWNERS[owner],
        "POSTGRES_USER": "briareus_fixture",
        "POSTGRES_PASSWORD": "fixture-only-no-real-credential",
    }


class ScopedDevOwnerInventoryContractTests(unittest.TestCase):
    def test_three_exact_allowed_owner_names(self) -> None:
        self.assertEqual(
            inventory._OWNERS,
            {
                "access": "briareus_access",
                "platform": "briareus_platform",
                "resources": "briareus_resources",
            },
        )
        self.assertNotIn("briareus_rauthy", inventory._OWNERS.values())
        self.assertNotIn("briareus_files", inventory._OWNERS.values())

    def test_valid_existing_application_postgres_env_without_any_new_key(self) -> None:
        with patch.dict(os.environ, _fixture(), clear=True):
            self.assertEqual(inventory._connection_contract("platform")[0], "briareus_fixture")

    def test_foreign_database_and_provider_database_fail_closed(self) -> None:
        for target in ("briareus_rauthy", "briareus_files", "briareus_identity", "briareus_dev"):
            env = _fixture()
            env["POSTGRES_DB"] = target
            with patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                inventory._connection_contract("platform")

    def test_wrong_port_or_host_fails_before_connect(self) -> None:
        for key, bad_value in (
            ("POSTGRES_HOST", "127.0.0.1"),
            ("POSTGRES_HOST", "other-project-postgres"),
            ("POSTGRES_PORT", "5433"),
        ):
            env = _fixture()
            env[key] = bad_value
            with patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                inventory._connection_contract("platform")

    def test_empty_secret_or_bad_user_rejected(self) -> None:
        for key, value in (("POSTGRES_PASSWORD", ""), ("POSTGRES_USER", "name;rm")):
            env = _fixture()
            env[key] = value
            with patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                inventory._connection_contract("platform")

    def test_unknown_owner_rejected_before_connection(self) -> None:
        with patch.dict(os.environ, _fixture(), clear=True):
            for owner in ("rauthy", "files", "identity", "runtime"):
                with self.assertRaises(ValueError):
                    inventory._connection_contract(owner)


class _FakeReadonlyTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, _type: object, _value: object, _tb: object) -> None:
        return None


class _ForeignOwnedDbConnection:
    def transaction(self, *, isolation: str, readonly: bool) -> _FakeReadonlyTransaction:
        assert isolation == "repeatable_read" and readonly is True
        return _FakeReadonlyTransaction()

    async def fetchrow(self, query: str) -> dict[str, str]:
        assert "current_database()" in query and "current_user" in query
        return {"db": "briareus_platform", "role": "briareus_fixture"}

    async def fetchval(self, query: str) -> str:
        assert "pg_get_userbyid(datdba)" in query
        return "unrelated_postgres_role"

    async def fetch(self, _query: str) -> None:
        raise AssertionError("foreign owner must reject before any table enumeration")


class ReadonlySqlOwnerProofTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreign_owned_database_denied_before_any_table_content(self) -> None:
        with self.assertRaises(ValueError):
            await inventory.inspect_connection(
                _ForeignOwnedDbConnection(), "platform", "briareus_fixture"
            )


if __name__ == "__main__":
    unittest.main()
