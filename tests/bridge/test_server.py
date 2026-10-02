from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client, FastMCP
from starlette.testclient import TestClient

from bridge import server as bridge_server
from bridge.server import _build_auth_reverse_proxy, app, mcp
from common.mcp_surfaces import MCP_SURFACE_PATHS
from common.runtime_policy_contracts import McpRuntimePolicy


@pytest.mark.asyncio
async def test_bridge_ping() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_ping", {})

    assert result.data is not None
    assert result.data["status"] == "ok"
    assert result.data["service"] == "mcp-bridge"


@pytest.mark.asyncio
async def test_bridge_root_is_map_not_backend_namespace() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()

    names = {tool.name for tool in tools}
    assert {
        "bridge_ping",
        "bridge_build_info",
        "bridge_backends",
        "bridge_tools",
        "bridge_call",
        "bridge_capabilities",
    } <= names
    assert "github_agent_status" not in names
    assert "accounts" not in names
    assert "file_status" not in names
    assert "curl_request" not in names


@pytest.mark.asyncio
async def test_bridge_capabilities_publish_only_supported_public_surfaces() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_capabilities", {})

    assert result.data is not None
    surfaces = set(result.data["public_surfaces"])
    assert set(MCP_SURFACE_PATHS.values()) <= surfaces
    assert "/admin" in surfaces
    assert "/ghidra/mcp" not in surfaces


def test_http_app_mounts_expected_public_surfaces() -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert {
        "/github",
        "/gitlab",
        "/files",
        "/web",
        "/analysis",
        "/admin",
        "/admin/{path:path}",
    } <= paths
    assert "/ghidra" not in paths
    assert "/curl" not in paths


def test_mounted_analysis_http_app_runs_fastmcp_lifespan() -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1"},
        },
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/analysis/mcp",
            json=payload,
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    assert "Task group is not initialized" not in response.text


def test_auth_proxy_targets_compose_auth_service() -> None:
    proxy = _build_auth_reverse_proxy()

    assert proxy.base_url == "http://auth:8000"


@pytest.mark.asyncio
async def test_gateway_proxy_uses_managed_mcp_timeout(monkeypatch) -> None:
    monkeypatch.setattr(
        bridge_server._management,
        "mcp_runtime_policy",
        lambda: McpRuntimePolicy(call_timeout_seconds=7),
    )

    proxy = bridge_server._proxy("test", "http://backend.example.test/mcp")
    client = await proxy.client_factory()

    assert client._session_kwargs["read_timeout_seconds"] == 7.0


@pytest.mark.asyncio
async def test_gateway_timeout_falls_back_to_five_seconds(monkeypatch) -> None:
    def broken_policy():
        raise ValueError("management unavailable")

    monkeypatch.setattr(bridge_server._management, "mcp_runtime_policy", broken_policy)

    assert await bridge_server._backend_timeout_seconds() == 5.0


@pytest.mark.asyncio
async def test_gateway_proxy_returns_timeout_error_instead_of_hanging(monkeypatch) -> None:
    slow = FastMCP("slow-backend")

    @slow.tool
    async def slow_tool() -> str:
        await asyncio.sleep(1)
        return "late"

    async def short_timeout() -> float:
        return 0.05

    monkeypatch.setattr(bridge_server, "_backend_timeout_seconds", short_timeout)
    proxy = bridge_server._proxy_target("slow", slow)

    with pytest.raises(Exception, match="timed out"):
        async with Client(proxy) as client:
            await client.call_tool("slow_tool", {})
