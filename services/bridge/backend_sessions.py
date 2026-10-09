from __future__ import annotations

import asyncio
import math
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, Literal

import mcp.types as mt
from fastmcp import FastMCP
from fastmcp.client.client import CallToolResult
from fastmcp.server.providers.proxy import ProxyClient
from opentelemetry import trace

BackendTarget = str | FastMCP[Any]
TimeoutProvider = Callable[[], Awaitable[float]]


class _ReusableProxyClient(ProxyClient[Any]):
    """One proxy client whose backend MCP session survives individual calls."""

    def __init__(
        self,
        target: BackendTarget,
        *,
        release: Callable[[_ReusableProxyClient], None],
        name: str,
        catalog_ttl_seconds: float,
    ) -> None:
        super().__init__(target, timeout=300, mode="auto", name=name, cache=True)
        self._release = release
        self._persistent_hold = False
        self._lease_active = False
        self._configured_timeout = 300.0
        self._catalog_ttl_seconds = max(0.0, float(catalog_ttl_seconds))
        self._tool_catalog_cache: tuple[float, list[mt.Tool]] | None = None
        self.connect_count = 0
        self.catalog_refresh_count = 0

    async def prepare(self, timeout_seconds: float) -> None:
        timeout_seconds = max(1.0, float(timeout_seconds))
        task = self._session_state.session_task
        dead = task is not None and task.done()
        if self._persistent_hold and dead:
            await super()._disconnect(force=True)
            self._persistent_hold = False
            self._tool_catalog_cache = None
        if timeout_seconds != self._configured_timeout:
            if self._persistent_hold:
                await super()._disconnect(force=True)
                self._persistent_hold = False
            self._session_kwargs["read_timeout_seconds"] = timeout_seconds
            self._configured_timeout = timeout_seconds

    async def list_tools(
        self,
        max_pages: int = 250,
        *,
        cache_mode: Literal["use", "refresh", "bypass"] = "use",
    ) -> list[mt.Tool]:
        now = time.monotonic()
        cached = self._tool_catalog_cache
        if (
            cache_mode == "use"
            and self._catalog_ttl_seconds > 0
            and cached is not None
            and cached[0] > now
        ):
            trace.get_current_span().set_attribute("mcp.backend.proxy_catalog_cache_hit", True)
            return list(cached[1])
        trace.get_current_span().set_attribute("mcp.backend.proxy_catalog_cache_hit", False)
        tools = list(await super().list_tools(max_pages=max_pages, cache_mode=cache_mode))
        self.catalog_refresh_count += 1
        if self._catalog_ttl_seconds > 0 and cache_mode != "bypass":
            self._tool_catalog_cache = (
                time.monotonic() + self._catalog_ttl_seconds,
                tools,
            )
        return list(tools)

    def lease(self) -> None:
        if self._lease_active:
            raise RuntimeError("proxy client is already leased")
        self._lease_active = True

    def _release_lease(self) -> None:
        if not self._lease_active:
            return
        self._lease_active = False
        self._release(self)

    async def __aenter__(self) -> _ReusableProxyClient:
        if not self._lease_active:
            raise RuntimeError("proxy client must be leased from its pool")
        try:
            reused = self._persistent_hold
            trace.get_current_span().set_attribute("mcp.backend.session_reused", reused)
            if not self._persistent_hold:
                await super()._connect()  # type: ignore[no-untyped-call]
                self._persistent_hold = True
                self.connect_count += 1
            await super()._connect()  # type: ignore[no-untyped-call]
            return self
        except BaseException:
            self._release_lease()
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
            self._release_lease()

    async def shutdown(self) -> None:
        if self._lease_active:
            raise RuntimeError("cannot shut down a leased proxy client")
        if self._persistent_hold:
            await super()._disconnect(force=True)
            self._persistent_hold = False
        self._tool_catalog_cache = None


class ProxyClientPool:
    """Small persistent MCP session pool for one proxied backend."""

    def __init__(
        self,
        target: BackendTarget,
        *,
        name: str,
        timeout_provider: TimeoutProvider,
        size: int = 2,
        catalog_ttl_seconds: float = 10.0,
    ) -> None:
        if size < 1:
            raise ValueError("proxy client pool size must be >= 1")
        self.name = name
        self.timeout_provider = timeout_provider
        self._queue: asyncio.Queue[_ReusableProxyClient] = asyncio.Queue(maxsize=size)
        self._clients: tuple[_ReusableProxyClient, ...] = tuple(
            _ReusableProxyClient(
                target,
                release=self._release,
                name=f"{name}-backend-{index + 1}",
                catalog_ttl_seconds=catalog_ttl_seconds,
            )
            for index in range(size)
        )
        for client in self._clients:
            self._queue.put_nowait(client)
        self._closed = False
        self._shutdown_complete = False
        self._close_lock = asyncio.Lock()

    @property
    def connect_count(self) -> int:
        return sum(client.connect_count for client in self._clients)

    @property
    def catalog_refresh_count(self) -> int:
        return sum(client.catalog_refresh_count for client in self._clients)

    async def acquire(self) -> ProxyClient[Any]:
        if self._closed:
            raise RuntimeError(f"proxy client pool is closed: {self.name}")
        started = time.monotonic()
        # Prevent an MCP request from waiting without bound when the entire
        # backend proxy pool is leased by slow or disconnected calls.
        try:
            async with asyncio.timeout(5.0):
                raw_timeout = float(await self.timeout_provider())
            wait_timeout = min(300.0, max(1.0, raw_timeout)) if math.isfinite(raw_timeout) else 5.0
        except Exception:
            wait_timeout = 5.0
        try:
            client = await asyncio.wait_for(self._queue.get(), timeout=wait_timeout)
        except TimeoutError as exc:
            raise RuntimeError(f"backend proxy pool exhausted: {self.name}") from exc
        wait_ms = (time.monotonic() - started) * 1000
        span = trace.get_current_span()
        span.set_attribute("mcp.backend.pool", self.name)
        span.set_attribute("mcp.backend.pool_wait_ms", wait_ms)
        span.set_attribute("mcp.backend.pool_size", len(self._clients))
        try:
            if self._closed:
                raise RuntimeError(f"backend proxy pool is closed: {self.name}")
            # Acquire ownership BEFORE an await in prepare(). Otherwise
            # concurrent lifespan shutdown could treat this checked-out
            # client as idle and close it while it is being configured.
            client.lease()
            async with asyncio.timeout(wait_timeout):
                await client.prepare(wait_timeout)
        except BaseException:
            if client._lease_active:
                client._release_lease()
            elif not self._closed:
                self._queue.put_nowait(client)
            raise
        return client

    def _release(self, client: _ReusableProxyClient) -> None:
        if self._closed:
            return
        self._queue.put_nowait(client)

    async def close(self) -> None:
        # `closed` stops new leases; failed cleanup must remain retryable.
        # Do not permanently mark shutdown complete when borrowed clients
        # prevent a clean closure on the first attempt.
        async with self._close_lock:
            if self._shutdown_complete:
                return
            self._closed = True
            deadline = time.monotonic() + 5.0
            while any(client._lease_active for client in self._clients):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(0.05, remaining))
            available = [client for client in self._clients if not client._lease_active]
            try:
                async with asyncio.timeout(5.0):
                    await asyncio.gather(*(client.shutdown() for client in available))
            except Exception as exc:
                raise RuntimeError(f"backend proxy shutdown failed: {self.name}") from exc
            if any(client._lease_active for client in self._clients):
                # A later explicit close can finish after the borrower exits.
                # Never forcibly mutate an unknown in-flight backend call.
                raise RuntimeError(f"backend proxy shutdown has active leases: {self.name}")
            self._shutdown_complete = True

    @asynccontextmanager
    async def lifespan(self, _server: FastMCP[Any]) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await self.close()


class BackendClientSession:
    """Lazy persistent FastMCP client for root bridge forwarding."""

    def __init__(self, target: BackendTarget, *, name: str) -> None:
        from fastmcp import Client

        self.name = name
        self._client: Client[Any] = Client(
            target,
            name=f"bridge-{name}-backend",
            timeout=300,
            mode="auto",
            cache=True,
        )
        self._connect_lock = asyncio.Lock()
        self._call_lock = asyncio.Lock()
        self._calls_active = 0
        self._closing = False
        self._connected = False
        self.connect_count = 0

    async def _enter_call(self) -> None:
        async with self._call_lock:
            if self._closing:
                raise RuntimeError(f"backend client session closing: {self.name}")
            self._calls_active += 1

    async def _exit_call(self) -> None:
        async with self._call_lock:
            self._calls_active -= 1

    async def _ensure_connected(self, timeout_seconds: float) -> None:
        task = self._client._session_state.session_task
        dead = task is not None and task.done()
        if self._connected and not dead:
            trace.get_current_span().set_attribute("mcp.backend.session_reused", True)
            return
        async with self._connect_lock:
            task = self._client._session_state.session_task
            dead = task is not None and task.done()
            if self._connected and not dead:
                trace.get_current_span().set_attribute("mcp.backend.session_reused", True)
                return
            trace.get_current_span().set_attribute("mcp.backend.session_reused", False)
            if self._connected:
                try:
                    async with asyncio.timeout(5.0):
                        await self._client._disconnect(force=True)
                finally:
                    self._connected = False
            async with asyncio.timeout(max(1.0, timeout_seconds)):
                await self._client._connect()  # type: ignore[no-untyped-call]
            self._connected = True
            self.connect_count += 1

    async def list_tools(self, timeout_seconds: float) -> list[Any]:
        await self._enter_call()
        try:
            await self._ensure_connected(timeout_seconds)
            async with asyncio.timeout(max(1.0, timeout_seconds)):
                return list(await self._client.list_tools())
        finally:
            await self._exit_call()

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float,
    ) -> CallToolResult:
        await self._enter_call()
        try:
            await self._ensure_connected(timeout_seconds)
            return await self._client.call_tool(
                tool_name,
                arguments,
                timeout=timeout_seconds,
            )
        except BaseException:
            task = self._client._session_state.session_task
            if task is not None and task.done():
                async with self._connect_lock:
                    if self._connected:
                        try:
                            async with asyncio.timeout(5.0):
                                await self._client._disconnect(force=True)
                        finally:
                            self._connected = False
            raise
        finally:
            await self._exit_call()

    async def close(self) -> None:
        async with self._call_lock:
            self._closing = True
        deadline = time.monotonic() + 5.0
        while True:
            async with self._call_lock:
                active = self._calls_active
            if not active:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # Keep closing=True; a subsequent close may finish after the
                # client returns, without interrupting an unknown mutation.
                raise RuntimeError(f"backend client has active calls: {self.name}")
            await asyncio.sleep(min(0.05, remaining))
        async with self._connect_lock:
            if not self._connected:
                return
            try:
                async with asyncio.timeout(5.0):
                    await self._client._disconnect(force=True)
            finally:
                self._connected = False
