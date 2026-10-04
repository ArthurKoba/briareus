from __future__ import annotations

from common.models import JsonObject

from .actions_diagnostics import GitHubActionsDiagnosticsClient
from .actions_mutations import GitHubActionsMutationClient
from .contents import GitHubContentsClient
from .github_collab import GitHubCollabClient
from .github_history import GitHubHistoryMixin
from .issues import GitHubIssueClient
from .refs import GitHubRefsClient
from .runs import GitHubRunClient


class GitHubActionsClient(
    GitHubHistoryMixin,
    GitHubCollabClient,
    GitHubContentsClient,
    GitHubRefsClient,
    GitHubIssueClient,
    GitHubRunClient,
    GitHubActionsDiagnosticsClient,
    GitHubActionsMutationClient,
):
    """Full GitHub client composed from repository, review, history, and Actions capabilities."""

    def merge_pull_request(
        self,
        repository: str,
        number: int,
        merge_method: str = "squash",
        commit_title: str | None = None,
        commit_message: str | None = None,
        expected_head_sha: str | None = None,
    ) -> JsonObject:
        return super().merge_pull_request(
            repository,
            number,
            merge_method,
            commit_title,
            commit_message,
            expected_head_sha,
        )
