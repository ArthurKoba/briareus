from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastmcp.server.providers.proxy import ProxyClient

from common.runtime_policy_contracts import BrowserRuntimePolicy
from modules.web.external_browser_proxy import (
    ExternalBrowserProxyRuntime,
    _PersistentPlaywrightProxyClient,
)


def policy(**overrides: object) -> BrowserRuntimePolicy:
    values: dict[str, object] = {
        "external_enabled": True,
        "external_mcp_url": "http://192.0.2.10:8931/mcp",
        "call_timeout_seconds": 300,
        "auto_disconnect_enabled": False,
        "idle_timeout_seconds": 300,
        "profile_dir_name": "Default",
        "extension_token_configured": False,
    }
    values.update(overrides)
    return BrowserRuntimePolicy.model_validate(values)


class ExternalBrowserProxyTests(unittest.TestCase):
    def test_policy_rejects_non_http_endpoint(self) -> None:
        with self.assertRaises(ValueError):
            policy(external_mcp_url="ws://example.test/mcp")

    def test_transport_normalizes_host_header_without_port(self) -> None:
        client = _PersistentPlaywrightProxyClient(policy())
        transport = client.transport
        self.assertEqual(transport.url, "http://192.0.2.10:8931/mcp")
        self.assertEqual(transport.headers.get("Host"), "192.0.2.10")

    def test_status_redacts_endpoint_path_and_secret_state(self) -> None:
        current = policy(
            external_mcp_url="http://192.0.2.10:8931/private/mcp?token=x",
            extension_token_configured=True,
        )

        async def provider() -> BrowserRuntimePolicy:
            return current

        async def scenario() -> None:
            runtime = ExternalBrowserProxyRuntime(provider)
            status = await runtime.status()
            self.assertEqual(status["endpoint_origin"], "http://192.0.2.10:8931")
            self.assertEqual(status["extension_token_configured"], True)
            self.assertNotIn("private", repr(status))
            self.assertNotIn("token=x", repr(status))

        asyncio.run(scenario())

    def test_disabled_policy_refuses_upstream_client(self) -> None:
        current = policy(external_enabled=False)

        async def provider() -> BrowserRuntimePolicy:
            return current

        async def scenario() -> None:
            runtime = ExternalBrowserProxyRuntime(provider)
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                await runtime._ensure_client()

        asyncio.run(scenario())

    def test_client_reuses_one_persistent_session(self) -> None:
        client = _PersistentPlaywrightProxyClient(policy())

        async def scenario() -> None:
            with patch.object(
                ProxyClient, "_connect", new_callable=AsyncMock
            ) as connect_mock, patch.object(
                ProxyClient, "_disconnect", new_callable=AsyncMock
            ) as disconnect_mock:
                first = await client.acquire()
                await first.__aenter__()
                await first.__aexit__(None, None, None)
                second = await client.acquire()
                await second.__aenter__()
                await second.__aexit__(None, None, None)
                self.assertEqual(client.connect_count, 1)
                # One persistent hold + one reference-counted enter per lease.
                self.assertEqual(connect_mock.await_count, 3)
                self.assertEqual(disconnect_mock.await_count, 2)
                await client.shutdown()
                self.assertEqual(disconnect_mock.await_count, 3)

        asyncio.run(scenario())

    def test_runtime_replaces_client_when_policy_changes(self) -> None:
        current = policy()

        async def provider() -> BrowserRuntimePolicy:
            return current

        async def scenario() -> None:
            nonlocal current
            runtime = ExternalBrowserProxyRuntime(provider)
            first = await runtime._ensure_client()
            with patch.object(first, "shutdown", new_callable=AsyncMock) as shutdown:
                current = policy(call_timeout_seconds=450)
                second = await runtime._ensure_client()
                self.assertIsNot(first, second)
                shutdown.assert_awaited_once()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
