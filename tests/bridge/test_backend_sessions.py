from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client, FastMCP
from fastmcp.server.providers.proxy import FastMCPProxy

from bridge.backend_sessions import ProxyClientPool


@pytest.mark.asyncio
async def test_proxy_client_pool_reuses_backend_session_across_calls() -> None:
    backend = FastMCP("backend")

    @backend.tool
    async def echo(value: str) -> str:
        return value

    async def timeout() -> float:
        return 2.0

    pool = ProxyClientPool(backend, name="test", timeout_provider=timeout, size=1)
    proxy = FastMCPProxy(client_factory=pool.acquire, lifespan=pool.lifespan)

    async with Client(proxy) as client:
        assert (await client.call_tool("echo", {"value": "one"})).data == "one"
        assert (await client.call_tool("echo", {"value": "two"})).data == "two"
        assert pool.connect_count == 1

    assert pool._closed is True


@pytest.mark.asyncio
async def test_proxy_client_pool_preserves_parallelism_with_separate_sessions() -> None:
    backend = FastMCP("backend")
    entered = 0
    both_entered = asyncio.Event()

    @backend.tool
    async def overlap() -> str:
        nonlocal entered
        entered += 1
        if entered == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=1)
        return "ok"

    async def timeout() -> float:
        return 2.0

    pool = ProxyClientPool(backend, name="parallel", timeout_provider=timeout, size=2)
    proxy = FastMCPProxy(client_factory=pool.acquire, lifespan=pool.lifespan)

    async with Client(proxy) as client:
        results = await asyncio.gather(
            client.call_tool("overlap", {}),
            client.call_tool("overlap", {}),
        )
        assert [result.data for result in results] == ["ok", "ok"]
        assert pool.connect_count == 2


@pytest.mark.asyncio
async def test_proxy_client_pool_caches_tool_catalog_for_short_ttl() -> None:
    backend = FastMCP("catalog-backend")

    @backend.tool
    async def echo(value: str) -> str:
        return value

    async def timeout() -> float:
        return 2.0

    pool = ProxyClientPool(
        backend,
        name="catalog",
        timeout_provider=timeout,
        size=1,
        catalog_ttl_seconds=10,
    )
    leased = await pool.acquire()
    async with leased as client:
        first = await client.list_tools()
        second = await client.list_tools()

    assert [tool.name for tool in first] == ["echo"]
    assert [tool.name for tool in second] == ["echo"]
    assert pool.catalog_refresh_count == 1
    await pool.close()
