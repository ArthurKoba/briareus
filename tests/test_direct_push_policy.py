from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from common.settings import GitHubPolicySettings, GitLabSettings
from modules.github.github_identity import GitHubPrettyIdentityClient
from modules.github.refs import GitHubRefsClient
from modules.gitlab.policy import require_mutable_branch
from modules.gitlab.repository import GitLabRepositoryClient


class DirectPushPolicyTests(unittest.TestCase):
    def test_empty_defaults_and_explicit_overrides(self) -> None:
        self.assertEqual(GitHubPolicySettings().protected_branches, frozenset())
        self.assertEqual(GitLabSettings().protected_branches, frozenset())
        self.assertEqual(
            GitHubPolicySettings(
                GITHUB_AGENT_PROTECTED_BRANCHES="main,MASTER",
            ).protected_branches,
            frozenset({"main", "master"}),
        )
        self.assertEqual(require_mutable_branch("main", frozenset()), "main")

    def test_github_protected_flag_is_informational(self) -> None:
        fake = SimpleNamespace(
            _assert_allowed=lambda repo: repo,
            _repo_request=lambda *_args, **_kwargs: (200, {"protected": True}),
            protected_branches=frozenset(),
        )
        policy = GitHubRefsClient._branch_policy(fake, "org/repo", "main")
        self.assertTrue(policy["github_protected"])
        self.assertTrue(policy["mutation_allowed"])
        fake.protected_branches = frozenset({"main"})
        policy = GitHubRefsClient._branch_policy(fake, "org/repo", "main")
        self.assertFalse(policy["mutation_allowed"])

    def test_github_push_removes_only_old_managed_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "checkout"
            hook = repo / ".git" / "hooks" / "pre-push"
            hook.parent.mkdir(parents=True)
            hook.write_text(
                "#!/bin/sh\n# koba-managed-local-git-guard\nexit 1\n",
                encoding="utf-8",
            )

            def git(*args: str) -> str:
                if args[0] == "branch":
                    return "main"
                if args[0] == "push":
                    self.assertFalse(hook.exists())
                    return "ok"
                if args[0] == "rev-parse":
                    return "a" * 40
                return ""

            values = {
                "koba.github.repository": "org/repo",
                "koba.github.accountId": "agent",
                "koba.github.transportAuthorized": "true",
            }
            fake = SimpleNamespace(
                public_only=False,
                account_id="agent",
                workspace_root=root,
                protected_branches=frozenset(),
                _assert_allowed=lambda repo: repo,
                _local_git_path=lambda _destination: repo,
                _git_optional_output=lambda _path, *args: values.get(args[-1], ""),
                _git_output=lambda _path, *args: git(*args),
                _assert_branch_mutation_allowed=lambda _repo, branch: branch,
            )
            result = GitHubPrettyIdentityClient.push_local_git(fake, "org/repo", "checkout")
            self.assertTrue(result["pushed"])

    def test_gitlab_push_keeps_unmanaged_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "checkout"
            hook = repo / ".git" / "hooks" / "pre-push"
            hook.parent.mkdir(parents=True)
            hook.write_text("#!/bin/sh\n# owner custom hook\nexit 0\n", encoding="utf-8")
            values = {
                "koba.gitlab.project": "team/repo",
                "koba.gitlab.accountId": "agent",
                "koba.gitlab.transportAuthorized": "true",
            }

            def git(*args: str) -> str:
                if args[0] == "branch":
                    return "main"
                if args[0] == "push":
                    self.assertTrue(hook.exists())
                    return "ok"
                if args[0] == "rev-parse":
                    return "a" * 40
                return ""

            fake = SimpleNamespace(
                anonymous_only=False,
                profile=SimpleNamespace(profile_id="agent"),
                workspace_root=root,
                protected_branches=frozenset(),
                _local_git_path=lambda _destination: repo,
                _git_optional_output=lambda _path, *args: values.get(args[-1], ""),
                _git_output=lambda _path, *args: git(*args),
            )
            result = GitLabRepositoryClient.push_local_git(
                fake,
                "team/repo",
                "checkout",
            )
            self.assertTrue(result["pushed"])


if __name__ == "__main__":
    unittest.main()
