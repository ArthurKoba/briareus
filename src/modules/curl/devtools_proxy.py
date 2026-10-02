from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import cast

import mcp.types as mt
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.providers.proxy import FastMCPProxy, ProxyClient
from fastmcp.tools import Tool, ToolResult

from common.settings import BrowserSettings

from .browser import BrowserError, BrowserManager

CHROME_DEVTOOLS_MCP_VERSION = "1.10.1"


class DeveloperAccessMiddleware(Middleware):
    """Gate the official Chrome DevTools MCP behind operator-controlled access."""

    def __init__(self, browser: BrowserManager, transport: StdioTransport) -> None:
        self.browser = browser
        self.transport = transport

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        try:
            tools = await call_next(context)
            state = (
                "Developer access is ON. "
                if self.browser.developer_access_effective
                else "Developer access is OFF; ask the operator to enable it before use. "
            )
            prefix = f"Koba privileged browser developer tool. {state}"
            return [
                tool.model_copy(update={"description": prefix + (tool.description or "")})
                for tool in tools
            ]
        finally:
            if not self.browser.developer_access_effective:
                disconnect = cast(Callable[[], Awaitable[None]], self.transport.disconnect)
                await disconnect()

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        try:
            self.browser.require_developer_access()
        except BrowserError as exc:
            disconnect = cast(Callable[[], Awaitable[None]], self.transport.disconnect)
            await disconnect()
            raise ToolError(str(exc)) from exc

        # The browser is lazy. Ensure the private CDP endpoint exists before the
        # upstream server attempts to connect to it.
        await self.browser.status()
        try:
            return await call_next(context)
        except Exception:
            # A timed-out or failed upstream request can leave the kept-alive stdio
            # session wedged. Tear it down so the next call starts a clean official
            # chrome-devtools-mcp process while preserving the original error.
            disconnect = cast(Callable[[], Awaitable[None]], self.transport.disconnect)
            await disconnect()
            raise


class DevToolsProxyRuntime:
    """Thin gated proxy around Google's official chrome-devtools-mcp server."""

    def __init__(self, browser: BrowserManager, settings: BrowserSettings) -> None:
        self.browser = browser
        self.transport = StdioTransport(
            command="node",
            args=[
                str(settings.devtools_mcp_script_path),
                "--browser-url=http://127.0.0.1:9222",
                "--category-extensions=true",
                "--memory-debugging=true",
                "--workspace=/workspace",
                "--file-navigations=false",
                "--performance-crux=false",
                "--usage-statistics=false",
            ],
            cwd="/workspace",
            keep_alive=True,
            log_file=Path("/browser/chrome-devtools-mcp.log"),
        )

        def client_factory() -> ProxyClient[StdioTransport]:
            return ProxyClient(
                self.transport,
                timeout=120,
                mode="auto",
                name="koba-chrome-devtools-upstream",
            )

        self.server = FastMCPProxy(
            client_factory=client_factory,
            name="chrome-devtools-upstream",
            provider_error_strategy="warn",
            identity="upstream",
        )
        self.server.middleware.insert(
            0,
            DeveloperAccessMiddleware(browser, self.transport),
        )
        browser.add_privileged_access_hook(self._on_access_change)

    async def _on_access_change(self, enabled: bool) -> None:
        if not enabled:
            disconnect = cast(Callable[[], Awaitable[None]], self.transport.disconnect)
            await disconnect()
