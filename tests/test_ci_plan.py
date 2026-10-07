from __future__ import annotations

import unittest

from scripts.ci_plan import plan


class CiPlanTest(unittest.TestCase):
    def test_authorization_change_runs_authorization_integration(self) -> None:
        result = plan(["services/authorization/provider.py"])
        self.assertTrue(result["run_authorization_integration"])
        self.assertEqual(result["integration_suites"], ["authorization"])

    def test_gateway_only_change_skips_postgres_integration(self) -> None:
        result = plan(["services/bridge/server.py"])
        self.assertFalse(result["run_authorization_integration"])
        self.assertEqual(result["integration_suites"], [])

    def test_unrelated_provider_change_skips_postgres_integration(self) -> None:
        result = plan(["services/modules/github/github_agent.py"])
        self.assertFalse(result["run_authorization_integration"])

    def test_common_change_runs_all_integration_suites(self) -> None:
        result = plan(["services/common/settings.py"])
        self.assertTrue(result["run_authorization_integration"])

    def test_authorization_integration_test_change_runs_suite(self) -> None:
        result = plan(["tests/test_postgres_authorization_access.py"])
        self.assertTrue(result["run_authorization_integration"])

    def test_force_full_runs_all_integration_suites(self) -> None:
        result = plan([], force_full=True)
        self.assertEqual(result["integration_suites"], ["authorization"])


if __name__ == "__main__":
    unittest.main()
