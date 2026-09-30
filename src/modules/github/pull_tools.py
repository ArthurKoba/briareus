from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .github_actions import GitHubActionsClient


def register_github_pull_tools(
    mcp: FastMCP,
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub agent list pull requests", annotations=read_annotations)
    def github_agent_list_pull_requests(
        account_id: str,
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> JsonObject:
        """List same-repository pull requests."""
        return client_factory(account_id).list_pull_requests(repository, state, per_page, page)

    @mcp.tool(title="GitHub agent get pull request", annotations=read_annotations)
    def github_agent_get_pull_request(account_id: str, repository: str, number: int) -> JsonObject:
        """Read pull request metadata."""
        return client_factory(account_id).get_pull_request(repository, number)

    @mcp.tool(title="GitHub agent create pull request", annotations=write_annotations)
    def github_agent_create_pull_request(
        account_id: str,
        repository: str,
        title: str,
        head: str,
        base: str,
        body: str = "",
        draft: bool = False,
    ) -> JsonObject:
        """Create a pull request whose head/base branches are in the same repository."""
        return client_factory(account_id).create_pull_request(
            repository, title, head, base, body, draft
        )

    @mcp.tool(title="GitHub agent update pull request", annotations=write_annotations)
    def github_agent_update_pull_request(
        account_id: str,
        repository: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        base: str | None = None,
    ) -> JsonObject:
        """Update title/body/state/base of a same-repository pull request."""
        return client_factory(account_id).update_pull_request(
            repository, number, title, body, state, base
        )

    @mcp.tool(title="GitHub agent pull request files", annotations=read_annotations)
    def github_agent_pull_files(account_id: str, repository: str, number: int) -> JsonObject:
        """List changed files and patches for a pull request."""
        return client_factory(account_id).list_pull_files(repository, number)

    @mcp.tool(title="GitHub agent pull request comment", annotations=write_annotations)
    def github_agent_add_pull_comment(
        account_id: str,
        repository: str,
        number: int,
        body: str,
    ) -> JsonObject:
        """Add a top-level conversation comment to a pull request."""
        return client_factory(account_id).add_pull_comment(repository, number, body)

    @mcp.tool(title="GitHub agent list reviews", annotations=read_annotations)
    def github_agent_list_reviews(account_id: str, repository: str, number: int) -> JsonObject:
        """List submitted reviews for a pull request."""
        return client_factory(account_id).list_reviews(repository, number)

    @mcp.tool(title="GitHub agent update pull branch", annotations=write_annotations)
    def github_agent_update_pull_branch(
        account_id: str,
        repository: str,
        number: int,
        expected_head_sha: str | None = None,
    ) -> JsonObject:
        """Update a pull request branch with changes from its base branch."""
        return client_factory(account_id).update_pull_branch(repository, number, expected_head_sha)

    @mcp.tool(title="GitHub agent check runs", annotations=read_annotations)
    def github_agent_check_runs(account_id: str, repository: str, ref: str) -> JsonObject:
        """List check-runs for a commit/ref."""
        return client_factory(account_id).check_runs(repository, ref)

    @mcp.tool(title="GitHub agent required checks", annotations=read_annotations)
    def github_agent_required_checks(account_id: str, repository: str, ref: str) -> JsonObject:
        """Verify configured required check-runs are completed successfully."""
        return client_factory(account_id).assert_required_checks(repository, ref)
