from __future__ import annotations

import contextlib
import logging
import os
import re
import threading
from collections.abc import Awaitable, Callable, Sequence
from typing import TextIO, cast

import mcp.types as mt
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.providers.proxy import FastMCPProxy, ProxyClient
from fastmcp.tools import Tool, ToolResult

from common.settings import BrowserSettings

from .browser import BrowserError, BrowserManager

CHROME_DEVTOOLS_MCP_VERSION = "1.10.1"


logger = logging.getLogger("mcp_bridge.web.devtools")

_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(authorization|cookie|set-cookie|token|api[-_]?key|secret|password)"
    r"\b\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)


def _redact_upstream_stderr(line: str) -> str:
    return _SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}=<redacted>", line)


class _DevToolsStderrForwarder:
    """Forward chrome-devtools-mcp stderr into the runtime OTLP logging pipeline."""

    def __init__(self) -> None:
        read_fd, write_fd = os.pipe()
        self._reader = os.fdopen(
            read_fd, "r", encoding="utf-8", errors="replace", buffering=1
        )
        self.stream: TextIO = os.fdopen(
            write_fd, "w", encoding="utf-8", errors="replace", buffering=1
        )
        self._thread = threading.Thread(
            target=self._run, name="chrome-devtools-mcp-stderr", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        for raw_line in self._reader:
            line = _redact_upstream_stderr(raw_line.rstrip())
            if not line:
                continue
            lowered = line.casefold()
            level = (
                logging.ERROR
                if any(
                    token in lowered
                    for token in ("error", "failed", "exception", "unknown argument")
                )
                else logging.INFO
            )
            logger.log(
                level,
                "chrome-devtools-mcp stderr: %s",
                line,
                extra={"mcp_component": "chrome-devtools-mcp"},
            )

    def close(self) -> None:
        if not self.stream.closed:
            self.stream.close()
        self._thread.join(timeout=1.0)
        if not self._reader.closed:
            self._reader.close()


class DeveloperAccessMiddleware(Middleware):
    """Gate the official Chrome DevTools MCP behind operator-controlled access."""

    _EXTENSION_ID = re.compile(r"Extension installed\. Id:\s*([a-p]{32})")

    def __init__(self, browser: BrowserManager, transport: StdioTransport) -> None:
        self.browser = browser
        self.transport = transport

    @staticmethod
    def _result_text(result: ToolResult) -> str:
        return "\n".join(
            item.text
            for item in result.content
            if isinstance(item, mt.TextContent)
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
            prefix = f"Koba privileged browser developer tool. {state}"
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

        # The browser is lazy. Ensure the private CDP endpoint exists before the
        # upstream server attempts to connect to it. A stale Playwright context
        # is recovered non-destructively before handing control to upstream.
        status = await self.browser.status()
        if not bool(status.get("running")):
            await self.browser.restart()

        tool_name = context.message.name
        arguments = context.message.arguments or {}
        try:
            result = await call_next(context)
            self.browser.set_developer_backend_connected(True)
            if tool_name == "install_extension":
                path_value = arguments.get("path")
                match = self._EXTENSION_ID.search(self._result_text(result))
                if isinstance(path_value, str) and match is not None:
                    extension_id = match.group(1)
                    self.browser.record_dev_extension(extension_id, path_value)
                    await self.browser.sync_dev_extension_user_scripts(extension_id)
            elif tool_name == "uninstall_extension":
                extension_id = arguments.get("id")
                if isinstance(extension_id, str):
                    self.browser.forget_dev_extension(extension_id)
            return result
        except Exception:
            # A timed-out or failed upstream request can leave the kept-alive stdio
            # session wedged. Tear it down and repair Chromium only if its own health
            # probes fail; preserve the original upstream error for the caller.
            await self._disconnect()
            with contextlib.suppress(Exception):
                await self.browser.recover_if_broken()
            raise


class DevToolsProxyRuntime:
    """Thin gated proxy around Google's official chrome-devtools-mcp server."""

    def __init__(self, browser: BrowserManager, settings: BrowserSettings) -> None:
        self.browser = browser
        self._stderr_forwarder = _DevToolsStderrForwarder()
        self.transport = StdioTransport(
            command="node",
            args=[
                str(settings.devtools_mcp_script_path),
                "--browser-url=http://127.0.0.1:9222",
                "--category-extensions=true",
                "--memory-debugging=true",
                "--workspace=/workspace",
                "--performance-crux=false",
                "--usage-statistics=false",
            ],
            cwd="/workspace",
            keep_alive=True,
            log_file=self._stderr_forwarder.stream,
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
        browser.add_restart_hook(self._disconnect)

    async def _disconnect(self) -> None:
        disconnect = cast(Callable[[], Awaitable[None]], self.transport.disconnect)
        await disconnect()
        self.browser.set_developer_backend_connected(False)

    async def _on_access_change(self, enabled: bool) -> None:
        if not enabled:
            await self._disconnect()
