from __future__ import annotations

import pytest
from fastmcp import FastMCP
from fastmcp.client import Client

from common.runtime_policy_contracts import GitHubRuntimePolicy
from modules.github.workflow_guard import (
    LOCAL_FIRST_GUIDANCE,
    REMOTE_SOURCE_MUTATION_DISABLED,
    GitHubLocalFirstMiddleware,
)


def _server(*, guidance: bool = True, remote_mutations: bool = True) -> FastMCP:
    server = FastMCP("workflow-guard-test")

    @server.tool()
    def github_agent_put_file() -> dict[str, bool]:
        """Write one file."""
        return {"ok": True}

    @server.tool()
    def github_agent_create_pull_request() -> dict[str, bool]:
        """Create one PR."""
        return {"ok": True}

    @server.tool()
    def github_checkout_repository() -> dict[str, bool]:
        """Checkout."""
        return {"ok": True}

    server.middleware.insert(
        0,
        GitHubLocalFirstMiddleware(
            lambda: GitHubRuntimePolicy(
                local_first_guidance=guidance,
                remote_source_mutations_enabled=remote_mutations,
            )
        ),
    )
    return server


@pytest.mark.asyncio
async def test_local_first_guidance_is_published_on_source_mutations_and_checkout() -> None:
    async with Client(_server()) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

        assert LOCAL_FIRST_GUIDANCE in (tools["github_agent_put_file"].description or "")
        assert "Preferred entry point for substantial source work" in (
            tools["github_checkout_repository"].description or ""
        )
        assert LOCAL_FIRST_GUIDANCE not in (
            tools["github_agent_create_pull_request"].description or ""
        )

        result = await client.call_tool("github_agent_put_file", {})
        text = "\n".join(getattr(block, "text", "") for block in result.content)
        assert LOCAL_FIRST_GUIDANCE in text
        assert result.meta is not None
        assert result.meta["koba/github-workflow"]["local_first_guidance"] is True


@pytest.mark.asyncio
async def test_remote_source_mutations_can_be_disabled_without_blocking_pr_control_plane() -> None:
    async with Client(_server(remote_mutations=False)) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert REMOTE_SOURCE_MUTATION_DISABLED in (tools["github_agent_put_file"].description or "")

        with pytest.raises(Exception, match="Remote GitHub source/history mutations are disabled"):
            await client.call_tool("github_agent_put_file", {})

        result = await client.call_tool("github_agent_create_pull_request", {})
        assert result.data == {"ok": True}


@pytest.mark.asyncio
async def test_guidance_can_be_disabled_while_remote_mutations_remain_available() -> None:
    async with Client(_server(guidance=False, remote_mutations=True)) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert LOCAL_FIRST_GUIDANCE not in (tools["github_agent_put_file"].description or "")
        result = await client.call_tool("github_agent_put_file", {})
        text = "\n".join(getattr(block, "text", "") for block in result.content)
        assert LOCAL_FIRST_GUIDANCE not in text
