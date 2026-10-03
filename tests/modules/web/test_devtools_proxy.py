from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import mcp.types as mt
import pytest
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool, ToolResult

from common.settings import BrowserSettings
from modules.files.workspace_store import WorkspaceFileStore
from modules.web.browser import BrowserManager
from modules.web.devtools_proxy import (
    CHROME_DEVTOOLS_MCP_VERSION,
    DeveloperAccessMiddleware,
    DevToolsProxyRuntime,
)


def _browser(tmp_path: Path) -> BrowserManager:
    return BrowserManager(
        workspace=WorkspaceFileStore(tmp_path / "workspace"),
        profile_dir=tmp_path / "profile",
        executable_path="/usr/bin/chromium",
        headless=True,
        timeout_ms=30_000,
        viewport_width=1440,
        viewport_height=900,
        max_snapshot_text_chars=30_000,
        max_snapshot_elements=250,
    )


class _FakeTransport:
    def __init__(self) -> None:
        self.disconnects = 0

    async def disconnect(self) -> None:
        self.disconnects += 1


def _context(name: str = "evaluate_script", arguments: dict[str, object] | None = None) -> Any:
    return cast(
        Any,
        SimpleNamespace(
            message=SimpleNamespace(name=name, arguments=arguments or {}),
        ),
    )


@pytest.mark.asyncio
async def test_devtools_middleware_blocks_when_developer_access_is_off(
    tmp_path: Path,
) -> None:
    browser = _browser(tmp_path)
    transport = _FakeTransport()
    middleware = DeveloperAccessMiddleware(
        browser,
        cast(StdioTransport, transport),
    )
    called = False

    async def call_next(_context: Any) -> ToolResult:
        nonlocal called
        called = True
        return ToolResult(content=[])

    with pytest.raises(ToolError, match="developer access is disabled"):
        await middleware.on_call_tool(_context(), call_next)

    assert transport.disconnects == 1
    assert called is False


@pytest.mark.asyncio
async def test_devtools_middleware_runs_upstream_only_with_effective_access(
    tmp_path: Path,
) -> None:
    browser = _browser(tmp_path)
    browser._operator_pages["owner"] = ""
    await browser.operator_set_developer_access("owner", True)
    transport = _FakeTransport()
    middleware = DeveloperAccessMiddleware(
        browser,
        cast(StdioTransport, transport),
    )
    status_calls = 0

    async def fake_status() -> dict[str, object]:
        nonlocal status_calls
        status_calls += 1
        return {"running": True}

    browser.status = fake_status  # type: ignore[method-assign]
    expected = ToolResult(content=[])

    async def call_next(_context: Any) -> ToolResult:
        return expected

    result = await middleware.on_call_tool(_context(), call_next)

    assert result is expected
    assert status_calls == 1
    assert transport.disconnects == 0



@pytest.mark.asyncio
async def test_devtools_middleware_disconnects_failed_upstream_session(
    tmp_path: Path,
) -> None:
    browser = _browser(tmp_path)
    browser._operator_pages["owner"] = ""
    await browser.operator_set_developer_access("owner", True)
    transport = _FakeTransport()
    middleware = DeveloperAccessMiddleware(
        browser,
        cast(StdioTransport, transport),
    )

    async def fake_status() -> dict[str, object]:
        return {"running": True}

    browser.status = fake_status  # type: ignore[method-assign]
    recover_calls = 0

    async def fake_recover() -> bool:
        nonlocal recover_calls
        recover_calls += 1
        return False

    browser.recover_if_broken = fake_recover  # type: ignore[method-assign]

    async def call_next(_context: Any) -> ToolResult:
        raise TimeoutError("upstream stalled")

    with pytest.raises(TimeoutError, match="upstream stalled"):
        await middleware.on_call_tool(_context(), call_next)

    assert transport.disconnects == 1
    assert recover_calls == 1
    assert browser.developer_backend_connected is False

@pytest.mark.asyncio
async def test_devtools_install_records_extension_for_browser_restart(tmp_path: Path) -> None:
    browser = _browser(tmp_path)
    browser._operator_pages["owner"] = ""
    await browser.operator_set_developer_access("owner", True)
    transport = _FakeTransport()
    middleware = DeveloperAccessMiddleware(
        browser,
        cast(StdioTransport, transport),
    )
    extension_dir = browser.workspace.root / "demo-extension"
    extension_dir.mkdir(parents=True)
    extension_id = "abcdefghijklmnopabcdefghijklmnop"

    async def fake_status() -> dict[str, object]:
        return {"running": True}

    browser.status = fake_status  # type: ignore[method-assign]

    async def call_next(_context: Any) -> ToolResult:
        return ToolResult(
            content=[
                mt.TextContent(
                    type="text",
                    text=f"Extension installed. Id: {extension_id}",
                )
            ]
        )

    result = await middleware.on_call_tool(
        _context("install_extension", {"path": str(extension_dir)}),
        call_next,
    )

    assert result.content
    assert browser.developer_backend_connected is True
    assert browser.dev_extensions() == [{"id": extension_id, "path": str(extension_dir)}]
    assert f"--load-extension={extension_dir}" in browser._browser_command()

    reloaded = _browser(tmp_path)
    assert reloaded.dev_extensions() == [{"id": extension_id, "path": str(extension_dir)}]


@pytest.mark.asyncio
async def test_devtools_uninstall_forgets_persistent_extension(tmp_path: Path) -> None:
    browser = _browser(tmp_path)
    browser._operator_pages["owner"] = ""
    await browser.operator_set_developer_access("owner", True)
    transport = _FakeTransport()
    middleware = DeveloperAccessMiddleware(
        browser,
        cast(StdioTransport, transport),
    )
    extension_dir = browser.workspace.root / "demo-extension"
    extension_dir.mkdir(parents=True)
    extension_id = "abcdefghijklmnopabcdefghijklmnop"
    browser.record_dev_extension(extension_id, str(extension_dir))

    async def fake_status() -> dict[str, object]:
        return {"running": True}

    browser.status = fake_status  # type: ignore[method-assign]

    async def call_next(_context: Any) -> ToolResult:
        return ToolResult(content=[])

    await middleware.on_call_tool(
        _context("uninstall_extension", {"id": extension_id}),
        call_next,
    )

    assert browser.dev_extensions() == []


def test_devtools_proxy_pins_official_server_and_restricts_workspace(tmp_path: Path) -> None:
    browser = _browser(tmp_path)
    script = tmp_path / "chrome-devtools-mcp.js"
    settings = BrowserSettings(
        profile_dir=tmp_path / "profile",
        devtools_mcp_script_path=script,
    )
    runtime = DevToolsProxyRuntime(browser, settings)

    assert CHROME_DEVTOOLS_MCP_VERSION == "1.10.1"
    assert runtime.transport.command == "node"
    assert runtime.transport.args[0] == str(script)
    assert "--browser-url=http://127.0.0.1:9222" in runtime.transport.args
    assert "--category-extensions=true" in runtime.transport.args
    assert "--category-experimental-third-party=true" not in runtime.transport.args
    assert "--memory-debugging=true" in runtime.transport.args
    assert "--experimental-devtools=true" not in runtime.transport.args
    assert "--workspace=/workspace" in runtime.transport.args
    assert "--file-navigations=false" in runtime.transport.args
    assert "--performance-crux=false" in runtime.transport.args
    assert runtime.transport.env is None


@pytest.mark.asyncio
async def test_devtools_catalog_stays_visible_but_upstream_disconnects_when_access_is_off(
    tmp_path: Path,
) -> None:
    browser = _browser(tmp_path)
    transport = _FakeTransport()
    middleware = DeveloperAccessMiddleware(
        browser,
        cast(StdioTransport, transport),
    )

    async def demo_tool() -> str:
        return "ok"

    upstream_tool = FunctionTool.from_function(
        demo_tool,
        name="evaluate_script",
        description="Evaluate JavaScript in the selected page.",
    )

    async def call_next(_context: Any):
        return [upstream_tool]

    tools = await middleware.on_list_tools(cast(Any, object()), call_next)

    assert len(tools) == 1
    assert tools[0].name == "evaluate_script"
    assert "Developer access is OFF" in (tools[0].description or "")
    assert transport.disconnects == 1
