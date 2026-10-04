from __future__ import annotations

import subprocess
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common.account_contracts import ResolvedAccount
from common.models import (
    JsonContainer,
    JsonObject,
    json_int,
    json_member_object,
    json_object,
    json_str,
    json_value,
)
from common.repository_checkout import RepositoryCheckoutError, resolve_workspace_destination
from common.settings import GitHubPolicySettings

from .github_actions import GitHubActionsClient
from .github_agent import GitHubAgentError

_GITHUB_API = "https://api.github.com"


class GitHubPrettyIdentityClient(GitHubActionsClient):
    @classmethod
    def from_account(
        cls,
        account: ResolvedAccount,
        policy: GitHubPolicySettings,
    ) -> GitHubPrettyIdentityClient:
        credential = account.credential.replace("\\n", "\n").strip()
        if not credential:
            raise GitHubAgentError("GitHub account has no credential")
        if account.auth_type == "github_token":
            return cls(
                account_id=account.id,
                token=credential,
                auth_type=account.auth_type,
                protected_branches=policy.protected_branches,
                required_checks=policy.required_checks,
                required_reviewers=policy.required_reviewers,
            )
        app_id = (account.external_id or "").strip()
        if not app_id:
            raise GitHubAgentError("GitHub App account has no APP_ID")
        return cls(
            app_id=app_id,
            private_key=credential,
            account_id=account.id,
            auth_type=account.auth_type,
            protected_branches=policy.protected_branches,
            required_checks=policy.required_checks,
            required_reviewers=policy.required_reviewers,
        )

    """Use the GitHub App display name for Git-authored objects.

    GitHub still exposes the immutable App actor login (for example
    ``koba-ai-agent[bot]``). Direct Git objects created by the bridge use the
    human-friendly GitHub App name as ``author.name``/``committer.name`` while
    retaining the GitHub-generated bot noreply email for stable attribution.
    """

    def _app_identity(self) -> JsonObject:
        if self.public_only:
            return {
                "source": "public_authenticated_reader" if self.token else "public_anonymous",
                "display_name": "public",
                "login": "public",
                "id": 0,
                "type": "Public",
                "name": "public",
                "email": "",
                "reader_account": self.public_reader_account,
                "transport_authenticated": bool(self.token),
            }
        cached = getattr(self, "_app_identity_cache", None)
        if isinstance(cached, dict):
            return dict(cached)

        if self.token:
            _, app = self._request(
                "GET",
                f"{_GITHUB_API}/user",
                token=self.token,
                auth_mode="user_token",
            )
            if not isinstance(app, dict):
                raise GitHubAgentError("unexpected GitHub user response")
            login = json_str(app.get("login")).strip()
            if not login:
                raise GitHubAgentError("GitHub user response has no login")
            display_name = json_str(app.get("name")).strip() or login
            user_id = json_int(app.get("id"))
            email = json_str(app.get("email")).strip() or (
                f"{user_id}+{login}@users.noreply.github.com"
            )
            token_identity: JsonObject = {
                "source": "github_token",
                "display_name": display_name,
                "login": login,
                "id": user_id,
                "type": json_str(app.get("type"), default="User") or "User",
                "name": display_name,
                "email": email,
            }
            self._app_identity_cache = dict(token_identity)
            return token_identity

        _, app = self._request(
            "GET",
            f"{_GITHUB_API}/app",
            token=self._app_jwt(),
            auth_mode="github_app_jwt",
        )
        if not isinstance(app, dict):
            raise GitHubAgentError("unexpected GitHub App response")

        slug = json_str(app.get("slug")).strip()
        display_name = json_str(app.get("name")).strip()
        if not slug:
            raise GitHubAgentError("GitHub App response has no slug")
        if not display_name:
            display_name = slug

        login = f"{slug}[bot]"
        _, bot = self._request(
            "GET",
            f"{_GITHUB_API}/users/{urllib.parse.quote(login, safe='')}",
            token=self._any_installation_token(),
            auth_mode="installation",
        )
        if not isinstance(bot, dict):
            raise GitHubAgentError("unable to resolve GitHub App bot identity")
        try:
            bot_id = json_int(bot.get("id"), field="bot.id")
        except ValueError as exc:
            raise GitHubAgentError("unable to resolve GitHub App bot identity") from exc
        if bot_id <= 0:
            raise GitHubAgentError("unable to resolve GitHub App bot identity")
        app_identity: JsonObject = {
            "source": "current_agent_app",
            "app_id": self.app_id,
            "slug": slug,
            "display_name": display_name,
            "login": login,
            "id": bot_id,
            "type": json_str(bot.get("type"), default="Bot") or "Bot",
            "name": display_name,
            "email": f"{bot_id}+{login}@users.noreply.github.com",
        }
        self._app_identity_cache = dict(app_identity)
        return app_identity

    def _agent_app_identity(self) -> JsonObject:
        """Compatibility hook used by history/admin policy code."""
        return self._app_identity()

    def _git_signature(self) -> dict[str, str]:
        identity = self._app_identity()
        return {
            "name": str(identity["name"]),
            "email": str(identity["email"]),
        }

    def _local_git_path(self, destination: str) -> Path:
        try:
            target = resolve_workspace_destination(self.workspace_root, destination)
        except RepositoryCheckoutError as exc:
            raise GitHubAgentError(
                str(exc).replace("destination", "workspace destination")
            ) from exc
        if not (target / ".git").exists():
            raise GitHubAgentError(f"workspace is not a Git checkout: {destination}")
        return target

    @staticmethod
    def _git_output(target: Path, *args: str, env: dict[str, str] | None = None) -> str:
        result = subprocess.run(
            ["git", "-C", str(target), *args],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[-2048:]
            raise GitHubAgentError(
                f"git command failed with exit code {result.returncode}: {detail}"
            )
        return (result.stdout or result.stderr).strip()

    def _git_optional_output(self, target: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(target), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 1 and not (result.stderr or result.stdout).strip():
            return ""
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[-2048:]
            raise GitHubAgentError(
                f"git command failed with exit code {result.returncode}: {detail}"
            )
        return (result.stdout or result.stderr).strip()

    @staticmethod
    def _expected_remote(repository: str) -> str:
        return f"https://github.com/{repository}.git"

    def authorize_local_git(
        self, repository: str, destination: str, *, remote: str = "origin"
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        if self.public_only:
            raise GitHubAgentError(
                "local Git write authorization requires an authenticated GitHub account"
            )
        target = self._local_git_path(destination)
        remote = remote.strip() or "origin"
        expected = self._expected_remote(repository)
        current = self._git_output(target, "remote", "get-url", remote)
        normalized = current.removesuffix(".git")
        accepted = {
            f"https://github.com/{repository}",
            f"ssh://git@github.com/{repository}",
            f"git@github.com:{repository}",
        }
        if normalized not in accepted:
            raise GitHubAgentError(
                f"workspace remote {remote!r} does not match repository {repository!r}: {current}"
            )

        signature = self._git_signature()
        git_dir = target / ".git"
        credential_file = git_dir / "koba-credentials"
        hook = git_dir / "hooks" / "pre-push"
        hook.parent.mkdir(parents=True, exist_ok=True)
        marker = "# koba-managed-local-git-guard"
        if hook.exists():
            existing = hook.read_text(encoding="utf-8", errors="replace")
            if marker not in existing:
                raise GitHubAgentError(
                    "existing pre-push hook is not managed by Koba; refusing to overwrite it"
                )

        token = self.token or self._installation_token(repository)
        credential_file.write_text(
            f"https://x-access-token:{token}@github.com/{repository}.git\n",
            encoding="utf-8",
        )
        credential_file.chmod(0o600)
        reserved = " ".join(sorted(self.protected_branches))
        hook.write_text(
            "#!/bin/sh\n"
            f"{marker}\n"
            "set -eu\n"
            f'reserved=" {reserved} "\n'
            "while read local_ref local_oid remote_ref remote_oid; do\n"
            '  case "$remote_ref" in\n'
            "    refs/heads/*) branch=${remote_ref#refs/heads/} ;;\n"
            "    *) continue ;;\n"
            "  esac\n"
            '  case "$reserved" in\n'
            '    *" $branch "*) echo "push to reserved branch denied: $branch" >&2; exit 1 ;;\n'
            "  esac\n"
            "done\n",
            encoding="utf-8",
        )
        hook.chmod(0o700)

        helper = f"store --file={credential_file}"
        self._git_output(target, "config", "--local", "user.name", signature["name"])
        self._git_output(target, "config", "--local", "user.email", signature["email"])
        self._git_output(target, "config", "--local", f"remote.{remote}.url", expected)
        self._git_output(target, "config", "--local", "credential.helper", helper)
        self._git_output(target, "config", "--local", "credential.useHttpPath", "true")
        self._git_output(target, "config", "--local", "koba.github.repository", repository)
        self._git_output(target, "config", "--local", "koba.github.accountId", self.account_id)
        self._git_output(target, "config", "--local", "koba.github.transportAuthorized", "true")
        branch = self._git_output(target, "branch", "--show-current")
        return {
            "authorized": True,
            "repository": repository,
            "workspace": target.relative_to(self.workspace_root.resolve(strict=False)).as_posix(),
            "resolved_workspace_path": target.as_posix(),
            "remote": remote,
            "remote_url": expected,
            "branch": branch,
            "account_id": self.account_id,
            "credential_storage": "git_credential_store",
            "credential_file": credential_file.relative_to(target).as_posix(),
            "push_mode": "ordinary_git",
            "warning": (
                "Experimental local Git transport. Re-authorize the workspace when the "
                "short-lived GitHub credential expires. Existing GitHub mutation tools remain "
                "available until this path is fully accepted."
            ),
        }

    def push_local_git(
        self,
        repository: str,
        destination: str,
        *,
        branch: str = "",
        remote: str = "origin",
        set_upstream: bool = True,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        if self.public_only:
            raise GitHubAgentError("local Git push requires an authenticated GitHub account")
        target = self._local_git_path(destination)
        remote = remote.strip() or "origin"
        marker_repo = self._git_optional_output(
            target, "config", "--local", "--get", "koba.github.repository"
        )
        marker_account = self._git_optional_output(
            target, "config", "--local", "--get", "koba.github.accountId"
        )
        marker_enabled = self._git_optional_output(
            target, "config", "--local", "--get", "koba.github.transportAuthorized"
        )
        if (
            marker_repo != repository
            or marker_account != self.account_id
            or marker_enabled.casefold() != "true"
        ):
            raise GitHubAgentError(
                "workspace is not authorized for this GitHub account/repository; "
                "call github_authorize_local_git first"
            )
        current_branch = self._git_output(target, "branch", "--show-current")
        push_branch = (branch.strip() or current_branch).strip()
        if not push_branch:
            raise GitHubAgentError("cannot push a detached HEAD; specify a local branch")
        self._assert_branch_mutation_allowed(repository, push_branch)
        args = ["push", "--porcelain"]
        if set_upstream:
            args.append("--set-upstream")
        args += [remote, f"HEAD:refs/heads/{push_branch}"]
        output = self._git_output(target, *args)
        head = self._git_output(target, "rev-parse", "HEAD")
        return {
            "pushed": True,
            "repository": repository,
            "workspace": target.relative_to(self.workspace_root.resolve(strict=False)).as_posix(),
            "resolved_workspace_path": target.as_posix(),
            "remote": remote,
            "branch": push_branch,
            "head": head,
            "account_id": self.account_id,
            "credential_storage": "none",
            "git_output": output[-2048:],
            "warning": (
                "Experimental local Git transport. Existing GitHub mutation tools remain "
                "available until this path is fully accepted."
            ),
        }

    @staticmethod
    def _copy_payload(payload: object | None) -> JsonObject | None:
        if payload is None:
            return None
        try:
            return json_object(payload, context="GitHub request payload")
        except ValueError as exc:
            raise GitHubAgentError("GitHub request payload must be JSON-compatible") from exc

    def _repo_request(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, JsonContainer]:
        updated = self._copy_payload(payload)
        contents_prefix = f"/repos/{repository}/contents/"
        commit_path = f"/repos/{repository}/git/commits"
        tag_path = f"/repos/{repository}/git/tags"
        is_direct_commit = updated is not None and (
            (method in {"PUT", "DELETE"} and path.startswith(contents_prefix))
            or (method == "POST" and path == commit_path)
        )

        if updated is not None and is_direct_commit:
            signature = json_value(
                self._git_signature(),
                context="GitHub git signature",
            )
            updated.setdefault("author", signature)
            updated.setdefault("committer", signature)
        elif updated is not None and method == "POST" and path == tag_path:
            updated.setdefault(
                "tagger",
                json_value(
                    self._git_signature(),
                    context="GitHub tagger signature",
                ),
            )

        return super()._repo_request(
            repository,
            method,
            path,
            payload=updated if updated is not None else payload,
            allowed_errors=allowed_errors,
        )

    def account_capabilities(self) -> JsonObject:
        """Return provider-reported account permissions without requiring a repository."""
        if self.public_only:
            return {
                "account_id": "public",
                "auth_type": "public",
                "identity": {"login": "public", "type": "Public"},
                "provider_permissions": {"contents": "read"},
                "provider_permissions_known": True,
                "transport_auth": "authenticated_reader" if self.token else "anonymous",
                "reader_account": self.public_reader_account,
                "note": (
                    "Authenticated public GitHub access; read-only."
                    if self.token
                    else "Anonymous public GitHub access; read-only."
                ),
            }
        if self.token:
            _, user = self._request(
                "GET",
                f"{_GITHUB_API}/user",
                token=self.token,
                auth_mode="user_token",
            )
            payload = json_object(user, context="GitHub user response")
            return {
                "account_id": self.account_id,
                "auth_type": self.auth_type,
                "identity": {
                    "login": json_str(payload.get("login")),
                    "name": json_str(payload.get("name")),
                    "type": json_str(payload.get("type")),
                },
                "provider_permissions": {},
                "provider_permissions_known": False,
                "note": (
                    "GitHub user tokens do not expose one reliable account-global permission map; "
                    "effective rights are repository/resource dependent."
                ),
            }

        _, app = self._request(
            "GET",
            f"{_GITHUB_API}/app",
            token=self._app_jwt(),
            auth_mode="github_app_jwt",
        )
        payload = json_object(app, context="GitHub App response")
        permissions = json_member_object(payload, "permissions")
        return {
            "account_id": self.account_id,
            "auth_type": self.auth_type,
            "identity": {
                "app_id": self.app_id,
                "slug": json_str(payload.get("slug")),
                "name": json_str(payload.get("name")),
            },
            "provider_permissions": {key: json_str(value) for key, value in permissions.items()},
            "provider_permissions_known": True,
            "note": (
                "GitHub App permissions are the application ceiling; installation/repository "
                "selection can further reduce effective rights."
            ),
        }

    def list_repositories(self) -> JsonObject:
        if self.public_only:
            return {
                "auth_type": "public",
                "count": 0,
                "repositories": [],
                "note": "Public selector addresses repositories explicitly by owner/name.",
                "app_identity": self._app_identity(),
            }
        base_list = super().list_repositories
        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="github-list",
        ) as pool:
            repositories_future = pool.submit(base_list)
            identity_future = pool.submit(self._app_identity)
            result = repositories_future.result()
            result["app_identity"] = identity_future.result()
            return result

    def status(self, repository: str) -> JsonObject:
        base_status = super().status
        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="github-status",
        ) as pool:
            status_future = pool.submit(base_status, repository)
            identity_future = pool.submit(self._app_identity)
            result = status_future.result()
            result["app_identity"] = identity_future.result()
            return result
