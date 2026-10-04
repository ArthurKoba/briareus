from __future__ import annotations

from collections.abc import Callable, Sequence

import mcp.types as mt
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool, ToolResult

from common.runtime_policy_contracts import GitHubRuntimePolicy

LOCAL_FIRST_GUIDANCE = (
    "Koba GitHub workflow: for substantial source changes, prefer one local-first cycle: "
    "checkout/clone into the persistent Terminal workspace, edit and test locally, create local "
    "commits as needed, then publish once with an authenticated Git push or one batched atomic "
    "GitHub commit, followed by one PR. Avoid repeated per-file/per-commit GitHub API mutations; "
    "they waste API quota and fragment history."
)

REMOTE_SOURCE_MUTATION_DISABLED = (
    "Remote GitHub source/history mutations are disabled by policy. Use github_checkout_repository "
    "with mode='git', perform source work in Terminal, and publish through the configured Git "
    "transport. PR/review/issues/Actions control-plane tools remain available."
)

# These operations mutate repository source/history directly. Control-plane mutations such as
# creating PRs, comments, reviews, issues and Actions operations deliberately remain available.
SOURCE_MUTATION_TOOLS = frozenset(
    {
        "github_agent_create_branch",
        "github_agent_put_file",
        "github_agent_delete_file",
        "github_agent_put_binary_file",
        "github_agent_copy_files",
        "github_agent_commit_files",
        "github_agent_delete_branch",
        "github_agent_rename_branch",
        "github_agent_reset_branch",
        "github_agent_create_tag",
        "github_agent_delete_tag",
        "github_agent_fast_forward",
        "github_agent_merge_working_branches",
        "github_agent_update_pull_branch",
        "github_agent_update_pull_branch_with_method",
        "github_agent_rewrite_branch_identity",
        "github_agent_rewrite_branch_identity_graph",
        "github_admin_repoint_reserved_branch",
    }
)

GUIDANCE_TOOLS = SOURCE_MUTATION_TOOLS | {"github_checkout_repository"}


class GitHubLocalFirstMiddleware(Middleware):
    """Steer substantial Git work to local workspaces and optionally block REST source mutation."""

    def __init__(self, policy_provider: Callable[[], GitHubRuntimePolicy]) -> None:
        self.policy_provider = policy_provider

    def _description_prefix(self, tool_name: str, policy: GitHubRuntimePolicy) -> str:
        if tool_name == "github_checkout_repository":
            return (
                "Preferred entry point for substantial source work. Checkout with mode='git', "
                "continue in the persistent Terminal workspace, and publish once after validation. "
            )
        if tool_name in SOURCE_MUTATION_TOOLS:
            if not policy.remote_source_mutations_enabled:
                return (
                    "Remote source mutation is disabled by policy. "
                    + REMOTE_SOURCE_MUTATION_DISABLED
                    + " "
                )
            if policy.local_first_guidance:
                return LOCAL_FIRST_GUIDANCE + " "
        return ""

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        policy = self.policy_provider()
        if not policy.local_first_guidance and policy.remote_source_mutations_enabled:
            return tools
        adapted: list[Tool] = []
        for tool in tools:
            prefix = self._description_prefix(tool.name, policy)
            if not prefix:
                adapted.append(tool)
                continue
            adapted.append(
                tool.model_copy(update={"description": prefix + (tool.description or "")})
            )
        return adapted

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = context.message.name
        policy = self.policy_provider()
        if tool_name in SOURCE_MUTATION_TOOLS and not policy.remote_source_mutations_enabled:
            raise ToolError(REMOTE_SOURCE_MUTATION_DISABLED)

        result = await call_next(context)
        if not policy.local_first_guidance or tool_name not in GUIDANCE_TOOLS:
            return result

        guidance = (
            "Local-first workflow selected. Continue substantial edits/tests in Terminal "
            "and publish once."
            if tool_name == "github_checkout_repository"
            else LOCAL_FIRST_GUIDANCE
        )
        content = [*result.content, mt.TextContent(type="text", text=guidance)]
        meta = dict(result.meta or {})
        meta["koba/github-workflow"] = {
            "local_first_guidance": True,
            "remote_source_mutations_enabled": policy.remote_source_mutations_enabled,
        }
        return result.model_copy(update={"content": content, "meta": meta})
