from __future__ import annotations

import asyncio

import pytest
from fastmcp import FastMCP

from bridge.backend_router import BackendDescriptor, BackendRouter


async def _timeout() -> float:
    return 2.0


@pytest.mark.asyncio
async def test_backend_router_reuses_one_session_for_catalog_and_calls() -> None:
    backend = FastMCP("backend")

    @backend.tool
    async def echo(value: str) -> str:
        return value

    router = BackendRouter(
        (BackendDescriptor("demo", backend, "/demo/mcp", "demo"),),
        timeout_provider=_timeout,
    )
    try:
        first_catalog = await router.tools("demo")
        second_catalog = await router.tools("demo")
        first_call = await router.call("demo", "echo", {"value": "one"})
        second_call = await router.call("demo", "echo", {"value": "two"})

        assert first_catalog["count"] == second_catalog["count"] == 1
        assert first_call["result"] == {"result": "one"}
        assert second_call["result"] == {"result": "two"}
        assert router._sessions["demo"].connect_count == 1
    finally:
        await router.close()


@pytest.mark.asyncio
async def test_backend_router_refreshes_catalog_without_reconnecting() -> None:
    backend = FastMCP("backend")

    @backend.tool
    async def one() -> str:
        return "one"

    router = BackendRouter(
        (BackendDescriptor("demo", backend, "/demo/mcp", "demo"),),
        timeout_provider=_timeout,
    )
    try:
        assert (await router.tools("demo"))["count"] == 1

        @backend.tool
        async def two() -> str:
            return "two"

        assert (await router.tools("demo"))["count"] == 1
        assert (await router.tools("demo", refresh=True))["count"] == 2
        assert router._sessions["demo"].connect_count == 1
    finally:
        await router.close()


@pytest.mark.asyncio
async def test_backend_router_persistent_session_supports_parallel_calls() -> None:
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

    router = BackendRouter(
        (BackendDescriptor("demo", backend, "/demo/mcp", "demo"),),
        timeout_provider=_timeout,
    )
    try:
        results = await asyncio.gather(
            router.call("demo", "overlap"),
            router.call("demo", "overlap"),
        )
        assert [result["result"] for result in results] == [
            {"result": "ok"},
            {"result": "ok"},
        ]
        assert router._sessions["demo"].connect_count == 1
    finally:
        await router.close()
