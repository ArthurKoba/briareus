import pytest
from fastmcp import Client
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import bridge.server as server_module
from bridge.server import app, mcp


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
async def test_bridge_capabilities_publish_single_origin_paths() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_capabilities", {})

    assert result.data is not None
    assert {
        "/mcp",
        "/github/mcp",
        "/gitlab/mcp",
        "/files/mcp",
        "/web/mcp",
        "/analysis/mcp",
        "/ghidra/mcp",
        "/admin",
    } <= set(result.data["public_surfaces"])


def test_http_app_mounts_expected_public_surfaces() -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert {
        "/github",
        "/gitlab",
        "/files",
        "/web",
        "/analysis",
        "/ghidra",
        "/admin",
        "/admin/{path:path}",
    } <= paths
    assert "/http" not in paths
    assert "/curl" not in paths


class _FakeOAuthDiscovery:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def get_well_known_routes(self, mcp_path: str | None = None):
        assert mcp_path == "/mcp"

        async def metadata(_request):
            return JSONResponse({})

        return [
            Route(
                f"/.well-known/oauth-authorization-server{self.prefix}",
                metadata,
            ),
            Route(
                f"/.well-known/oauth-protected-resource{self.prefix}/mcp",
                metadata,
            ),
        ]


def test_oauth_surface_urls_are_path_scoped() -> None:
    settings = server_module.BridgeSettings(
        oauth_base_url="https://mcp.example.test/",
    )

    assert server_module._oauth_surface_url(settings, "root") == "https://mcp.example.test"
    assert (
        server_module._oauth_surface_url(settings, "analysis")
        == "https://mcp.example.test/analysis"
    )
    assert (
        server_module._oauth_surface_url(settings, "files")
        == "https://mcp.example.test/files"
    )


def test_oauth_discovery_covers_every_public_mcp_resource(monkeypatch) -> None:
    fake_auth = {
        surface: _FakeOAuthDiscovery(prefix)
        for surface, prefix in server_module._OAUTH_SURFACE_PREFIXES.items()
    }
    monkeypatch.setattr(server_module, "_auth_by_surface", fake_auth)

    paths = {
        getattr(route, "path", "")
        for route in server_module._oauth_discovery_routes()
    }

    assert "/.well-known/oauth-authorization-server" in paths
    assert "/.well-known/oauth-protected-resource/mcp" in paths
    for prefix in server_module._OAUTH_SURFACE_PREFIXES.values():
        if not prefix:
            continue
        assert f"/.well-known/oauth-authorization-server{prefix}" in paths
        assert f"/.well-known/oauth-protected-resource{prefix}/mcp" in paths


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
