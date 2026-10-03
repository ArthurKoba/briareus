from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastmcp import Client

from common.mcp_client_pool import PersistentMcpClientPool


class _FakeClient:
    def __init__(self, state: dict[str, int], *, fail_tool: str = "") -> None:
        self.state = state
        self.fail_tool = fail_tool

    async def __aenter__(self):
        self.state["enters"] += 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb
        self.state["exits"] += 1

    async def call_tool(self, name: str, arguments: dict[str, Any], **kwargs):
        del arguments, kwargs
        self.state["calls"] += 1
        if name == self.fail_tool:
            raise TimeoutError("backend stalled")
        return SimpleNamespace(content=[], structured_content={"tool": name})

    async def list_tools(self):
        self.state["lists"] += 1
        return [SimpleNamespace(name="one"), SimpleNamespace(name="two")]


def _factory(state: dict[str, int], *, fail_tool: str = ""):
    def build() -> Client[Any]:
        return cast(Client[Any], _FakeClient(state, fail_tool=fail_tool))

    return build


@pytest.mark.asyncio
async def test_persistent_mcp_pool_reuses_connected_session() -> None:
    state = {"enters": 0, "exits": 0, "calls": 0, "lists": 0}
    pool = PersistentMcpClientPool(_factory(state), name="test", size=1)

    await pool.call_tool("first", {})
    await pool.call_tool("second", {})
    tools = await pool.list_tools()

    assert [tool.name for tool in tools] == ["one", "two"]
    assert state == {"enters": 1, "exits": 0, "calls": 2, "lists": 1}
    assert pool.connect_count == 1

    await pool.close()
    assert state["exits"] == 1


@pytest.mark.asyncio
async def test_persistent_mcp_pool_resets_failed_session_before_retry() -> None:
    state = {"enters": 0, "exits": 0, "calls": 0, "lists": 0}
    fail = True

    def build() -> Client[Any]:
        nonlocal fail
        client = _FakeClient(state, fail_tool="fail" if fail else "")
        fail = False
        return cast(Client[Any], client)

    pool = PersistentMcpClientPool(build, name="test", size=1)

    with pytest.raises(TimeoutError, match="backend stalled"):
        await pool.call_tool("fail", {})
    await pool.call_tool("ok", {})

    assert state["enters"] == 2
    assert state["exits"] == 1
    assert pool.connect_count == 2
    await pool.close()
    assert state["exits"] == 2
