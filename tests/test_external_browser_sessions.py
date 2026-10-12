from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastmcp.client.transports import StreamableHttpTransport

from common.runtime_policy_contracts import BrowserRuntimePolicy
from modules.web.external_browser_proxy import (
    ExternalBrowserProxyRuntime,
    _PersistentPlaywrightProxyClient,
)


class _FakeLease:
    def __init__(self, *, failed_stage: str = "", tabs_error: bool = False) -> None:
        self.failed_stage = failed_stage
        self.tabs_error = tabs_error
        self.policy = BrowserRuntimePolicy()
        self.connected = True
        self.connect_count = 1
        self.last_activity_at = "2026-10-12T00:00:00Z"
        self.tab_calls = 0

    async def acquire(self) -> _FakeLease:
        if self.failed_stage == "mcp_initialize":
            raise TimeoutError("PRIVATE-SID-NOT-FOR-LOGGING")
        return self

    async def __aenter__(self) -> _FakeLease:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def list_tools(self) -> list[object]:
        if self.failed_stage == "tools_list":
            raise ConnectionError("PRIVATE-AUTH-HEADER")
        return ["browser_tabs"]

    async def call_tool(self, name: str, arguments: object, **_kwargs: object) -> object:
        assert name == "browser_tabs" and arguments == {"action": "list"}
        self.tab_calls += 1
        if self.failed_stage == "tabs_list":
            raise TimeoutError("PRIVATE-BROWSER-URL")
        return SimpleNamespace(is_error=self.tabs_error)


class ExternalBrowserSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = BrowserRuntimePolicy(
            external_enabled=True, external_mcp_url="http://localhost:8931/mcp"
        )

    def runtime(self, lease: _FakeLease | None = None) -> ExternalBrowserProxyRuntime:
        async def policy() -> BrowserRuntimePolicy:
            return self.policy

        runtime = ExternalBrowserProxyRuntime(policy)
        if lease is not None:
            lease.policy = self.policy
            runtime._client = lease  # type: ignore[assignment]
            runtime._client_policy = self.policy
        return runtime

    def test_status_does_not_create_upstream_session(self) -> None:
        status = asyncio.run(self.runtime().status())
        self.assertFalse(status["connected"])
        self.assertEqual(status["other_client_sessions"], "not_observable")
        self.assertEqual(status["tab_access_state"], "not_checked")
        self.assertIsNone(status["browser_ready"])
        self.assertEqual(status["grant_state"], "unverified")

    def test_successful_tab_probe_not_equivalent_to_grant(self) -> None:
        lease = _FakeLease()
        result = asyncio.run(self.runtime(lease).connect())
        self.assertTrue(result["ok"])
        self.assertTrue(result["browser_ready"])
        self.assertEqual(result["connection_state"], "tab_list_responded")
        self.assertEqual(result["grant_state"], "unverified")
        self.assertEqual(lease.tab_calls, 1)
        self.assertEqual(result["tool_count"], 1)

    def test_tabs_error_is_explicit_not_false_success(self) -> None:
        status = asyncio.run(self.runtime(_FakeLease(tabs_error=True)).connect())
        self.assertFalse(status["ok"])
        self.assertEqual(status["connection_state"], "tab_check_failed")
        self.assertEqual(status["last_error"]["code"], "BROWSER_TABS_FAILED")
        self.assertEqual(status["last_error"]["stage"], "tabs_list")
        self.assertTrue(status["connected"])

    def test_staged_failures_are_actionable_without_secrets(self) -> None:
        for stage, expected in [
            ("mcp_initialize", "UPSTREAM_TIMEOUT"),
            ("tools_list", "UPSTREAM_UNREACHABLE"),
            ("tabs_list", "UPSTREAM_TIMEOUT"),
        ]:
            with self.subTest(stage=stage):
                result = asyncio.run(self.runtime(_FakeLease(failed_stage=stage)).connect())
                self.assertFalse(result["ok"])
                error = result["last_error"]
                self.assertEqual(error["stage"], stage)
                self.assertEqual(error["code"], expected)
                self.assertTrue(error["next_action"])
                self.assertNotIn("PRIVATE", str(error))
                self.assertNotIn("PRIVATE", str(result))

    def test_http_error_is_stage_scoped(self) -> None:
        error = RuntimeError("PRIVATE-SID")
        error.response = SimpleNamespace(status_code=404)  # type: ignore[attr-defined]
        diagnostic = ExternalBrowserProxyRuntime._diagnose("tools_list", error)
        self.assertEqual(diagnostic["http_status"], 404)
        self.assertEqual(diagnostic["stage"], "tools_list")
        self.assertNotIn("PRIVATE", str(diagnostic))

    def test_default_http_host_is_not_overridden(self) -> None:
        with patch(
            "modules.web.external_browser_proxy.StreamableHttpTransport",
            wraps=StreamableHttpTransport,
        ) as transport:
            _PersistentPlaywrightProxyClient(self.policy)
        transport.assert_called_once_with(self.policy.external_mcp_url)


if __name__ == "__main__":
    unittest.main()
