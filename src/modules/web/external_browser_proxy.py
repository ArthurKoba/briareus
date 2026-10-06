from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from urllib.parse import urlsplit

from fastmcp import FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.providers.proxy import FastMCPProxy, ProxyClient

from common.models import JsonObject
from common.runtime_policy_contracts import BrowserRuntimePolicy

logger = logging.getLogger("mcp_bridge.web.external_browser")

PolicyProvider = Callable[[], Awaitable[BrowserRuntimePolicy]]


class _PersistentPlaywrightProxyClient(ProxyClient[StreamableHttpTransport]):
    """One serialized persistent Playwright MCP session for the selected endpoint."""

    def __init__(self, policy: BrowserRuntimePolicy) -> None:
        self.policy = policy
        parts = urlsplit(policy.external_mcp_url)
        host_header = parts.hostname or ""
        transport = StreamableHttpTransport(
            policy.external_mcp_url,
            headers={"Host": host_header} if host_header else None,
        )
        super().__init__(
            transport,
            timeout=float(policy.call_timeout_seconds),
            mode="auto",
            name="koba-external-playwright-upstream",
            cache=True,
        )
        self._lease_lock = asyncio.Lock()
        self._persistent_hold = False
        self._idle_task: asyncio.Task[None] | None = None
        self.connect_count = 0
        self.last_activity_at = ""

    @property
    def connected(self) -> bool:
        task = self._session_state.session_task
        return bool(self._persistent_hold and task is not None and not task.done())

    def _cancel_idle_task(self) -> None:
        task = self._idle_task
        self._idle_task = None
        if task is not None and not task.done():
            task.cancel()

    def _touch(self) -> None:
        self.last_activity_at = datetime.now(UTC).isoformat()

    def _schedule_idle_disconnect(self) -> None:
        self._cancel_idle_task()
        if not self.policy.auto_disconnect_enabled or not self.connected:
            return
        self._idle_task = asyncio.create_task(
            self._idle_disconnect(),
            name="external-browser-idle-disconnect",
        )

    async def _idle_disconnect(self) -> None:
        try:
            await asyncio.sleep(float(self.policy.idle_timeout_seconds))
            async with self._lease_lock:
                if self._persistent_hold:
                    await super()._disconnect(force=True)
                    self._persistent_hold = False
                    logger.info(
                        "External Playwright MCP session auto-disconnected after %ss idle",
                        self.policy.idle_timeout_seconds,
                    )
        except asyncio.CancelledError:
            raise
        finally:
            self._idle_task = None

    async def acquire(self) -> _PersistentPlaywrightProxyClient:
        await self._lease_lock.acquire()
        self._cancel_idle_task()
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
            self._touch()
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
            self._touch()
        finally:
            self._lease_lock.release()
            self._schedule_idle_disconnect()

    async def shutdown(self) -> None:
        self._cancel_idle_task()
        async with self._lease_lock:
            if self._persistent_hold:
                await super()._disconnect(force=True)
                self._persistent_hold = False
                logger.info("External Playwright MCP session disconnected")


class ExternalBrowserProxyRuntime:
    """Dynamic proxy to the official Playwright MCP configured by Admin API policy."""

    def __init__(self, policy_provider: PolicyProvider) -> None:
        self._policy_provider = policy_provider
        self._client: _PersistentPlaywrightProxyClient | None = None
        self._client_policy: BrowserRuntimePolicy | None = None
        self._state_lock = asyncio.Lock()

        async def client_factory() -> ProxyClient[StreamableHttpTransport]:
            client = await self._ensure_client()
            return await client.acquire()

        self.server: FastMCP[Any] = FastMCPProxy(
            client_factory=client_factory,
            name="external-playwright-upstream",
            provider_error_strategy="warn",
            identity="upstream",
            lifespan=self._lifespan,
        )

    async def _policy(self) -> BrowserRuntimePolicy:
        return await self._policy_provider()

    async def _ensure_client(self) -> _PersistentPlaywrightProxyClient:
        policy = await self._policy()
        if not policy.external_enabled:
            raise RuntimeError("external browser is disabled in Admin settings")
        async with self._state_lock:
            if self._client is not None and self._client_policy != policy:
                await self._client.shutdown()
                self._client = None
                self._client_policy = None
            if self._client is None:
                self._client = _PersistentPlaywrightProxyClient(policy)
                self._client_policy = policy
            return self._client

    @staticmethod
    def _origin(url: str) -> str:
        if not url:
            return ""
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port is not None else ""
        return f"{parts.scheme}://{host}{port}"

    async def status(self) -> JsonObject:
        policy = await self._policy()
        client = self._client if self._client_policy == policy else None
        return {
            "configured": bool(policy.external_mcp_url),
            "enabled": policy.external_enabled,
            "provider": "playwright-mcp",
            "namespace": "external",
            "endpoint_origin": self._origin(policy.external_mcp_url),
            "connected": client.connected if client is not None else False,
            "session_connect_count": client.connect_count if client is not None else 0,
            "last_activity_at": client.last_activity_at if client is not None else "",
            "call_timeout_seconds": policy.call_timeout_seconds,
            "auto_disconnect_enabled": policy.auto_disconnect_enabled,
            "idle_timeout_seconds": policy.idle_timeout_seconds,
            "profile_dir_name": policy.profile_dir_name,
            "extension_token_configured": policy.extension_token_configured,
        }

    async def connect(self) -> JsonObject:
        client = await self._ensure_client()
        lease = await client.acquire()
        async with lease:
            tools = await lease.list_tools()
            tabs = await lease.call_tool(
                "browser_tabs",
                {"action": "list"},
                timeout=float(client.policy.call_timeout_seconds),
                raise_on_error=False,
            )
        status = await self.status()
        status["tool_count"] = len(tools)
        status["browser_ready"] = not tabs.is_error
        return status

    async def disconnect(self) -> JsonObject:
        async with self._state_lock:
            client = self._client
            self._client = None
            self._client_policy = None
        if client is not None:
            await client.shutdown()
        return await self.status()

    async def reset(self) -> JsonObject:
        await self.disconnect()
        policy = await self._policy()
        if not policy.external_enabled:
            return await self.status()
        return await self.connect()

    @asynccontextmanager
    async def _lifespan(self, _server: FastMCP[Any]) -> AsyncIterator[None]:
        try:
            yield
        finally:
            with suppress(Exception):
                await self.disconnect()
