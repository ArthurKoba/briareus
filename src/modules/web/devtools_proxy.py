from __future__ import annotations

import asyncio
import contextlib
import re
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import cast

import httpx
import mcp.types as mt
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.providers.proxy import FastMCPProxy, ProxyClient
from fastmcp.tools import Tool, ToolResult
from websockets.asyncio.client import connect as connect_websocket

from common.models import JsonObject
from common.settings import BrowserSettings

from .browser import BrowserError, BrowserManager
from .devtools_target import (
    DevToolsTarget,
    DevToolsTargetError,
    browser_version_url,
    clear_target,
    load_target,
    normalize_external_target,
    save_target,
    target_public_status,
)

CHROME_DEVTOOLS_MCP_VERSION = "1.10.1"


class DeveloperAccessMiddleware(Middleware):
    """Gate the official Chrome DevTools MCP behind operator-controlled access."""

    _EXTENSION_ID = re.compile(r"Extension installed\. Id:\s*([a-p]{32})")

    def __init__(
        self,
        browser: BrowserManager,
        transport: StdioTransport,
        *,
        uses_managed_browser: Callable[[], bool],
        target_label: Callable[[], str],
    ) -> None:
        self.browser = browser
        self.transport = transport
        self.uses_managed_browser = uses_managed_browser
        self.target_label = target_label

    @staticmethod
    def _result_text(result: ToolResult) -> str:
        return "\n".join(
            item.text for item in result.content if isinstance(item, mt.TextContent)
        )

    async def _disconnect(self) -> None:
        disconnect = cast(Callable[[], Awaitable[None]], self.transport.disconnect)
        await disconnect()
        self.browser.set_developer_backend_connected(False)

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        try:
            tools = await call_next(context)
            self.browser.set_developer_backend_connected(True)
            state = (
                "Developer access is ON. "
                if self.browser.developer_access_effective
                else "Developer access is OFF; ask the operator to enable it before use. "
            )
            prefix = (
                f"Koba privileged browser developer tool. {state}"
                f"Current DevTools target: {self.target_label()}. "
            )
            return [
                tool.model_copy(update={"description": prefix + (tool.description or "")})
                for tool in tools
            ]
        finally:
            if not self.browser.developer_access_effective:
                await self._disconnect()

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        try:
            self.browser.require_developer_access()
        except BrowserError as exc:
            await self._disconnect()
            raise ToolError(str(exc)) from exc

        managed_target = self.uses_managed_browser()
        if managed_target:
            # The managed browser is lazy. Ensure its loopback CDP endpoint exists before
            # chrome-devtools-mcp attempts to connect. External targets are owned by the
            # operator and must never trigger local Chromium restart/recovery.
            status = await self.browser.status()
            if not bool(status.get("running")):
                await self.browser.restart()

        tool_name = context.message.name
        arguments = context.message.arguments or {}
        try:
            result = await call_next(context)
            self.browser.set_developer_backend_connected(True)
            if managed_target and tool_name == "install_extension":
                path_value = arguments.get("path")
                match = self._EXTENSION_ID.search(self._result_text(result))
                if isinstance(path_value, str) and match is not None:
                    extension_id = match.group(1)
                    self.browser.record_dev_extension(extension_id, path_value)
                    await self.browser.sync_dev_extension_user_scripts(extension_id)
            elif managed_target and tool_name == "uninstall_extension":
                extension_id = arguments.get("id")
                if isinstance(extension_id, str):
                    self.browser.forget_dev_extension(extension_id)
            return result
        except Exception:
            # A timed-out or failed upstream request can leave the kept-alive stdio
            # session wedged. Only repair Chromium when that managed browser was the
            # active target; an external browser remains entirely operator-owned.
            await self._disconnect()
            if managed_target:
                with contextlib.suppress(Exception):
                    await self.browser.recover_if_broken()
            raise


class DevToolsProxyRuntime:
    """Gated chrome-devtools-mcp proxy with switchable managed/external CDP target."""

    def __init__(self, browser: BrowserManager, _settings: BrowserSettings) -> None:
        self.browser = browser
        self._target_lock = asyncio.Lock()
        self.transport = StdioTransport(
            command=sys.executable,
            args=["-m", "modules.web.devtools_launcher"],
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
            DeveloperAccessMiddleware(
                browser,
                self.transport,
                uses_managed_browser=self.uses_managed_browser,
                target_label=self.target_label,
            ),
        )
        browser.add_privileged_access_hook(self._on_access_change)
        browser.add_restart_hook(self._disconnect)

    def _target(self) -> DevToolsTarget:
        return load_target()

    def uses_managed_browser(self) -> bool:
        try:
            return self._target().managed
        except DevToolsTargetError:
            return False

    def target_label(self) -> str:
        try:
            target = self._target()
        except DevToolsTargetError:
            return "invalid external target configuration"
        return "managed Chromium" if target.managed else "externally attached Chrome"

    async def target_status(self) -> JsonObject:
        try:
            target = self._target()
        except DevToolsTargetError as exc:
            return {
                "mode": "invalid",
                "error": str(exc),
                "developer_access": self.browser.developer_access_effective,
                "backend_connected": self.browser.developer_backend_connected,
            }
        return {
            **target_public_status(target),
            "developer_access": self.browser.developer_access_effective,
            "backend_connected": self.browser.developer_backend_connected,
        }

    async def connect_external(
        self,
        endpoint: str,
        ws_headers: dict[str, str] | None = None,
    ) -> JsonObject:
        self.browser.require_developer_access()
        try:
            target = normalize_external_target(endpoint, ws_headers)
        except DevToolsTargetError as exc:
            raise BrowserError(str(exc)) from exc
        probe = await self._probe_external(target)
        async with self._target_lock:
            save_target(target)
            await self._disconnect()
        return {
            **target_public_status(target),
            **probe,
            "developer_access": self.browser.developer_access_effective,
            "backend_connected": False,
        }

    async def disconnect_external(self) -> JsonObject:
        self.browser.require_developer_access()
        async with self._target_lock:
            clear_target()
            await self._disconnect()
        return await self.target_status()

    async def _probe_external(self, target: DevToolsTarget) -> JsonObject:
        if target.mode == "browser_url":
            return await self._probe_browser_url(target)
        if target.mode == "ws_endpoint":
            return await self._probe_ws_endpoint(target)
        raise BrowserError("managed browser is not an external DevTools target")

    @staticmethod
    async def _probe_browser_url(target: DevToolsTarget) -> JsonObject:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(5.0),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.get(browser_version_url(target))
            if response.status_code != 200:
                raise BrowserError(
                    f"external DevTools endpoint returned HTTP {response.status_code}"
                )
            payload = response.json()
        except BrowserError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise BrowserError("external DevTools browser URL is unreachable or invalid") from exc
        if not isinstance(payload, dict) or not isinstance(
            payload.get("webSocketDebuggerUrl"), str
        ):
            raise BrowserError("external DevTools endpoint did not expose webSocketDebuggerUrl")
        browser_name = payload.get("Browser")
        protocol = payload.get("Protocol-Version")
        return {
            "probe": "json/version",
            "reachable": True,
            "browser": browser_name if isinstance(browser_name, str) else "",
            "protocol_version": protocol if isinstance(protocol, str) else "",
        }

    @staticmethod
    async def _probe_ws_endpoint(target: DevToolsTarget) -> JsonObject:
        try:
            async with connect_websocket(
                target.endpoint,
                additional_headers=target.ws_headers or None,
                origin=None,
                proxy=None,
                max_size=1024 * 1024,
                open_timeout=5,
                close_timeout=2,
            ):
                pass
        except Exception as exc:
            raise BrowserError("external DevTools WebSocket endpoint is unreachable") from exc
        return {"probe": "websocket", "reachable": True}

    async def _disconnect(self) -> None:
        disconnect = cast(Callable[[], Awaitable[None]], self.transport.disconnect)
        await disconnect()
        self.browser.set_developer_backend_connected(False)

    async def _on_access_change(self, enabled: bool) -> None:
        if not enabled:
            await self._disconnect()
