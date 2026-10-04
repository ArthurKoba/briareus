from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client, FastMCP
from starlette.testclient import TestClient

from bridge import server as bridge_server
from bridge.server import (
    _MANAGEMENT_UI_URL,
    _browser_devtools_ui_proxy,
    _build_auth_reverse_proxy,
    _management_api_proxy,
    _management_ui_proxy,
    app,
    mcp,
)
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
    assert "/api" in surfaces
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
        "/api",
        "/api/{path:path}",
        "/api/realtime",
        "/api/browser/operator/ws",
        "/api/browser/cdp/{token}/page/{target_id}",
        "/api/browser/devtools/{path:path}",
        "/admin/api",
        "/admin/api/{path:path}",
    } <= paths
    assert "/ghidra" not in paths
    assert "/curl" not in paths
    assert "/admin/api/realtime" not in paths
    assert "/admin/api/browser/operator/ws" not in paths
    assert "/admin/browser/ws" not in paths


def test_management_public_routing_contract() -> None:
    assert _management_api_proxy.base_url == "http://management:8000"
    assert _management_api_proxy._upstream_path("/api/session") == "/admin/api/session"
    assert _management_api_proxy._upstream_path("/api/dashboard") == "/admin/api/dashboard"
    assert _management_api_proxy._upstream_path("/api/accounts/github") == (
        "/admin/api/accounts/github"
    )

    assert _browser_devtools_ui_proxy.base_url == "http://web:8000"
    assert (
        _browser_devtools_ui_proxy._upstream_path(
            "/api/browser/devtools/token/page/TARGET/devtools/inspector.html"
        )
        == "/cdp-ui/token/page/TARGET/devtools/inspector.html"
    )

    assert _MANAGEMENT_UI_URL == "http://management-ui:8080"
    assert _management_ui_proxy.base_url == _MANAGEMENT_UI_URL
    assert _management_ui_proxy._upstream_path("/admin") == "/"
    assert _management_ui_proxy._upstream_path("/admin/") == "/"
    assert _management_ui_proxy._upstream_path("/admin/assets/test.js") == "/assets/test.js"
    assert _management_ui_proxy._upstream_path("/admin/runtime-config.js") == "/runtime-config.js"
    # Old public API paths are frontend-owned after cutover, not management-owned.
    assert _management_ui_proxy._upstream_path("/admin/api/session") == "/api/session"
    with pytest.raises(ValueError):
        _management_api_proxy._upstream_path("/admin/api/session")


def test_mcp_public_namespaces_are_unchanged() -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert {
        "/github",
        "/gitlab",
        "/files",
        "/web",
        "/analysis",
        "/terminal",
        "/observability",
    } <= paths
    assert "" in paths  # Starlette stores the root mount path as an empty string.


@pytest.mark.asyncio
async def test_management_websocket_preserves_session_and_public_origin_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_relay(websocket: object, target_url: str, **kwargs: object) -> None:
        captured["websocket"] = websocket
        captured["target_url"] = target_url
        captured.update(kwargs)

    monkeypatch.setattr(bridge_server, "relay_websocket", fake_relay)

    class FakeWebSocket:
        def __init__(self) -> None:
            self.headers = {
                "cookie": "session=abc",
                "host": "mcp.koba-nexus.ru",
                "origin": "https://mcp.koba-nexus.ru",
                "x-forwarded-proto": "https",
            }

    websocket = FakeWebSocket()
    await bridge_server._management_websocket(  # type: ignore[arg-type]
        websocket, "/admin/api/realtime"
    )

    assert captured == {
        "websocket": websocket,
        "target_url": "ws://management:8000/admin/api/realtime",
        "headers": {
            "Cookie": "session=abc",
            "X-Forwarded-Host": "mcp.koba-nexus.ru",
            "X-Forwarded-Proto": "https",
        },
        "origin": "https://mcp.koba-nexus.ru",
    }


@pytest.mark.asyncio
async def test_public_management_websockets_target_internal_management_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, str]] = []

    async def fake_management_websocket(websocket: object, path: str) -> None:
        calls.append((websocket, path))

    monkeypatch.setattr(bridge_server, "_management_websocket", fake_management_websocket)
    marker = object()

    await bridge_server._api_realtime_websocket(marker)  # type: ignore[arg-type]
    await bridge_server._api_browser_operator_websocket(marker)  # type: ignore[arg-type]

    class FakeCdpWebSocket:
        def __init__(self) -> None:
            self.path_params = {"token": "signed-token", "target_id": "TARGET123"}

    cdp = FakeCdpWebSocket()
    await bridge_server._api_browser_cdp_websocket(cdp)  # type: ignore[arg-type]

    assert calls == [
        (marker, "/admin/api/realtime"),
        (marker, "/admin/api/browser/operator/ws"),
        (
            cdp,
            "/admin/api/browser/cdp/signed-token/page/TARGET123",
        ),
    ]


def test_management_route_priority_is_explicit() -> None:
    paths = [getattr(route, "path", "") for route in app.routes]
    assert paths.index("/api/realtime") < paths.index("/api/{path:path}")
    assert paths.index("/api/browser/operator/ws") < paths.index("/api/{path:path}")
    assert paths.index("/api/browser/cdp/{token}/page/{target_id}") < paths.index(
        "/api/{path:path}"
    )
    assert paths.index("/api/browser/devtools/{path:path}") < paths.index("/api/{path:path}")
    assert paths.index("/api/{path:path}") < paths.index("/admin/{path:path}")
    assert paths.index("/admin/api/{path:path}") < paths.index("/admin/{path:path}")


def test_old_public_admin_api_namespace_is_hard_404() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/admin/api/session")
        assert response.status_code == 404
        assert response.text == "Not Found"


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
async def test_gateway_timeout_uses_managed_mcp_policy(monkeypatch) -> None:
    monkeypatch.setattr(
        bridge_server._management,
        "mcp_runtime_policy",
        lambda: McpRuntimePolicy(call_timeout_seconds=7),
    )

    assert await bridge_server._backend_timeout_seconds() == 7.0


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
