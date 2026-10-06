from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any
from urllib.parse import urlsplit

from fastmcp import FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.providers.proxy import FastMCPProxy, ProxyClient

from common.models import JsonObject
from common.settings import BrowserSettings

logger = logging.getLogger("mcp_bridge.web.external_browser")


class _PersistentPlaywrightProxyClient(ProxyClient[StreamableHttpTransport]):
    """Serialize proxy calls through one persistent upstream MCP HTTP session."""

    def __init__(self, url: str, *, timeout_seconds: float) -> None:
        parts = urlsplit(url)
        host_header = parts.hostname or ""
        transport = StreamableHttpTransport(
            url,
            headers={"Host": host_header} if host_header else None,
        )
        super().__init__(
            transport,
            timeout=timeout_seconds,
            mode="auto",
            name="koba-external-playwright-upstream",
            cache=True,
        )
        self._lease_lock = asyncio.Lock()
        self._persistent_hold = False
        self.connect_count = 0

    async def acquire(self) -> _PersistentPlaywrightProxyClient:
        await self._lease_lock.acquire()
        return self

    async def __aenter__(self) -> _PersistentPlaywrightProxyClient:
        try:
            task = self._session_state.session_task
            if self._persistent_hold and task is not None and task.done():
                await super()._disconnect(force=True)
                self._persistent_hold = False
            if not self._persistent_hold:
                await super()._connect()  # type: ignore[no-untyped-call]
                self._persistent_hold = True
                self.connect_count += 1
                logger.info("External Playwright MCP session connected")
            await super()._connect()  # type: ignore[no-untyped-call]
            return self
        except BaseException:
            if self._lease_lock.locked():
                self._lease_lock.release()
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            await super()._disconnect()
        finally:
            self._lease_lock.release()

    async def shutdown(self) -> None:
        async with self._lease_lock:
            if self._persistent_hold:
                await super()._disconnect(force=True)
                self._persistent_hold = False
                logger.info("External Playwright MCP session disconnected")


class ExternalBrowserProxyRuntime:
    """Proxy the official Playwright MCP server running beside the user's Chrome."""

    def __init__(self, settings: BrowserSettings) -> None:
        self.url = settings.external_mcp_url
        self.timeout_seconds = settings.external_mcp_timeout_seconds
        self.enabled = bool(self.url)
        self._client: _PersistentPlaywrightProxyClient | None = None
        self.server: FastMCP[Any] | None = None

        if not self.enabled:
            return

        self._client = _PersistentPlaywrightProxyClient(
            self.url,
            timeout_seconds=self.timeout_seconds,
        )

        async def client_factory() -> ProxyClient[StreamableHttpTransport]:
            assert self._client is not None
            return await self._client.acquire()

        self.server = FastMCPProxy(
            client_factory=client_factory,
            name="external-playwright-upstream",
            provider_error_strategy="warn",
            identity="upstream",
            lifespan=self._lifespan,
        )

    def status(self) -> JsonObject:
        if not self.enabled:
            return {
                "configured": False,
                "provider": "playwright-mcp",
                "namespace": "external",
            }
        parts = urlsplit(self.url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port is not None else ""
        return {
            "configured": True,
            "provider": "playwright-mcp",
            "namespace": "external",
            "endpoint_origin": f"{parts.scheme}://{host}{port}",
            "session_connect_count": self._client.connect_count if self._client else 0,
        }

    @asynccontextmanager
    async def _lifespan(self, _server: FastMCP[Any]) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if self._client is not None:
                await self._client.shutdown()
