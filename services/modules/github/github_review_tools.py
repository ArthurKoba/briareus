from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .github_review import GitHubReviewClient


def register_github_review_tools(
    mcp: FastMCP,
    client_factory: Callable[[str], GitHubReviewClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    """Register rebase and detailed review tools."""

    @mcp.tool(title="GitHub agent update pull branch with method", annotations=write_annotations)
    def github_agent_update_pull_branch_method(
        account_id: str,
        repository: str,
        number: int,
        method: str = "MERGE",
        expected_head_sha: str | None = None,
    ) -> JsonObject:
        """Update a PR branch using MERGE or true REBASE through GitHub GraphQL."""
        return client_factory(account_id).update_pull_branch_graphql(
            repository,
            number,
            method,
            expected_head_sha,
        )

    @mcp.tool(title="GitHub agent conversation comments", annotations=read_annotations)
    def github_agent_list_conversation_comments(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """List top-level issue/PR conversation comments."""
        return client_factory(account_id).list_conversation_comments(repository, number)

    @mcp.tool(title="GitHub agent inline review comments", annotations=read_annotations)
    def github_agent_list_review_comments(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """List inline review comments for a pull request."""
        return client_factory(account_id).list_review_comments(repository, number)
