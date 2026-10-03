from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .github_identity import GitHubPrettyIdentityClient


def register_github_core_tools(
    mcp: FastMCP,
    client_factory: Callable[[str], GitHubPrettyIdentityClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub agent list repositories", annotations=read_annotations)
    def github_agent_list_repositories(account_id: str) -> JsonObject:
        """List repositories currently accessible to the selected GitHub account."""
        return client_factory(account_id).list_repositories()

    @mcp.tool(title="GitHub agent status", annotations=read_annotations)
    def github_agent_status(account_id: str, repository: str) -> JsonObject:
        """Verify access and basic repository metadata for the selected account."""
        return client_factory(account_id).status(repository)

    @mcp.tool(title="GitHub rate limits", annotations=read_annotations)
    def github_agent_rate_limits(account_id: str, repository: str = "") -> JsonObject:
        """Refresh and report GitHub API rate-limit buckets for the selected identity."""
        return client_factory(account_id).refresh_rate_limits(repository)

    @mcp.tool(title="GitHub agent get file", annotations=read_annotations)
    def github_agent_get_file(
        account_id: str,
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> JsonObject:
        """Read one UTF-8 repository file at an optional ref."""
        return client_factory(account_id).get_file(repository, path, ref)

    @mcp.tool(title="GitHub agent list branches", annotations=read_annotations)
    def github_agent_list_branches(account_id: str, repository: str) -> JsonObject:
        """List repository branches visible to the selected account."""
        return client_factory(account_id).list_branches(repository)

    @mcp.tool(title="GitHub agent create branch", annotations=write_annotations)
    def github_agent_create_branch(
        account_id: str,
        repository: str,
        branch: str,
        from_branch: str = "main",
    ) -> JsonObject:
        """Create a non-protected working branch from an existing branch or ref."""
        return client_factory(account_id).create_branch(repository, branch, from_branch)

    @mcp.tool(title="GitHub agent put file", annotations=write_annotations)
    def github_agent_put_file(
        account_id: str,
        repository: str,
        path: str,
        content: str,
        message: str,
        branch: str,
    ) -> JsonObject:
        """Create or update one UTF-8 file on a non-protected working branch."""
        return client_factory(account_id).put_file(repository, path, content, message, branch)

    @mcp.tool(title="GitHub agent delete file", annotations=destructive_annotations)
    def github_agent_delete_file(
        account_id: str,
        repository: str,
        path: str,
        message: str,
        branch: str,
    ) -> JsonObject:
        """Delete one file from a non-protected working branch."""
        return client_factory(account_id).delete_file(repository, path, message, branch)

    @mcp.tool(title="GitHub checkout repository", annotations=write_annotations)
    def github_checkout_repository(
        account_id: str,
        repository: str,
        destination: str,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> JsonObject:
        """Checkout a repository into the shared workspace.

        mode='snapshot' creates a shallow working tree without .git.
        mode='git' keeps full Git metadata and history.
        account_id may be a stable account alias.
        """
        return client_factory(account_id).checkout_repository(
            repository,
            destination,
            mode=mode,
            ref=ref,
            overwrite=overwrite,
        )

    @mcp.tool(title="GitHub agent compare refs", annotations=read_annotations)
    def github_agent_compare(
        account_id: str,
        repository: str,
        base: str,
        head: str,
    ) -> JsonObject:
        """Compare two refs and return commit/file differences."""
        return client_factory(account_id).compare(repository, base, head)

    @mcp.tool(title="GitHub agent fast-forward branch", annotations=write_annotations)
    def github_agent_fast_forward(
        account_id: str,
        repository: str,
        branch: str,
        to_ref: str,
    ) -> JsonObject:
        """Fast-forward a non-protected working branch to an existing descendant ref."""
        return client_factory(account_id).fast_forward(repository, branch, to_ref)
