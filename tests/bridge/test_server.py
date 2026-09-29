from __future__ import annotations

import pytest
from fastmcp import Client
from starlette.testclient import TestClient

from bridge.server import app, mcp
from common.mcp_surfaces import MCP_SURFACE_PATHS


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
