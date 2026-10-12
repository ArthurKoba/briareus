from __future__ import annotations

import base64
import subprocess
import urllib.parse
from pathlib import Path

from common.models import JsonObject, json_object
from common.repository_checkout import checkout_repository

from .api import GitLabApiClient
from .errors import GitLabError
from .models import GitLabCommitAction
from .policy import require_mutable_branch


class GitLabRepositoryClient(GitLabApiClient):
    def checkout_repository(
        self,
        project: str | int,
        destination: str,
        *,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> JsonObject:
        raw_project = str(project).strip().strip("/")
        if not raw_project:
            raise GitLabError("project is required")
        encoded_project = urllib.parse.quote(raw_project, safe="/-._~")
        clone_url = f"{self.profile.base_url.rstrip('/')}/{encoded_project}.git"

        auth_header = ""
        if not self.anonymous_only:
            token = self.profile.token()
            if self.profile.auth_type == "private_token":
                encoded = base64.b64encode(f"oauth2:{token}".encode()).decode("ascii")
                auth_header = f"Authorization: Basic {encoded}"
            elif self.profile.auth_type == "bearer":
                auth_header = f"Authorization: Bearer {token}"
            else:
                encoded = base64.b64encode(
                    f"gitlab-ci-token:{token}".encode()
                ).decode("ascii")
                auth_header = f"Authorization: Basic {encoded}"

        result = checkout_repository(
            clone_url,
            destination,
            workspace_root=self.workspace_root,
            mode=mode,
            ref=ref,
            overwrite=overwrite,
            auth_scope=self.profile.base_url.rstrip("/") + "/",
            auth_header=auth_header,
            fallback_without_auth=True,
        )
        result["project"] = raw_project
        result["profile_id"] = self.profile.profile_id
        return result

    def _local_git_path(self, destination: str) -> Path:
        root = self.workspace_root.resolve(strict=False)
        raw = destination.strip().replace("\\", "/").lstrip("/")
        if not raw:
            raise GitLabError("workspace destination is required")
        target = (root / raw).resolve(strict=False)
        if target == root or not target.is_relative_to(root):
            raise GitLabError("workspace destination escapes workspace root")
        if not (target / ".git").exists():
            raise GitLabError(f"workspace is not a Git checkout: {destination}")
        return target

    @staticmethod
    def _git_output(target: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(target), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[-2048:]
            raise GitLabError(
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
            raise GitLabError(
                f"git command failed with exit code {result.returncode}: {detail}"
            )
        return (result.stdout or result.stderr).strip()

    def _expected_remote(self, project: str) -> str:
        encoded_project = urllib.parse.quote(project.strip().strip("/"), safe="/-._~")
        return f"{self.profile.base_url.rstrip('/')}/{encoded_project}.git"

    def _git_signature(self) -> dict[str, str]:
        user = self.request("GET", "/user").data
        if not isinstance(user, dict):
            raise GitLabError("unexpected GitLab /user response")
        username = str(user.get("username") or "").strip()
        name = str(user.get("name") or username).strip()
        email = str(
            user.get("commit_email")
            or user.get("email")
            or user.get("public_email")
            or (f"{username}@users.noreply.gitlab.com" if username else "")
        ).strip()
        if not name or not email:
            raise GitLabError("unable to resolve Git identity from GitLab /user")
        return {"name": name, "email": email}

    def _credential_url(self, project: str) -> str:
        parsed = urllib.parse.urlsplit(self.profile.base_url)
        username = "gitlab-ci-token" if self.profile.auth_type == "job_token" else "oauth2"
        token = urllib.parse.quote(self.profile.token(), safe="")
        project_path = urllib.parse.quote(project.strip().strip("/"), safe="/-._~")
        base_path = parsed.path.rstrip("/")
        path = f"{base_path}/{project_path}.git"
        netloc = f"{urllib.parse.quote(username, safe='')}:{token}@{parsed.netloc}"
        return urllib.parse.urlunsplit((parsed.scheme, netloc, path, "", ""))

    def authorize_local_git(
        self,
        project: str | int,
        destination: str,
        *,
        remote: str = "origin",
    ) -> JsonObject:
        if self.anonymous_only:
            raise GitLabError(
                "local Git write authorization requires an authenticated GitLab account"
            )
        raw_project = str(project).strip().strip("/")
        if not raw_project:
            raise GitLabError("project is required")
        target = self._local_git_path(destination)
        remote = remote.strip() or "origin"
        expected = self._expected_remote(raw_project)
        current = self._git_output(target, "remote", "get-url", remote)
        if current.removesuffix(".git") != expected.removesuffix(".git"):
            raise GitLabError(
                f"workspace remote {remote!r} does not match project {raw_project!r}: {current}"
            )

        git_dir = target / ".git"
        credential_file = git_dir / "koba-gitlab-credentials"
        hook = git_dir / "hooks" / "pre-push"
        hook.parent.mkdir(parents=True, exist_ok=True)
        marker = "# koba-managed-gitlab-local-git-guard"
        if hook.exists():
            existing = hook.read_text(encoding="utf-8", errors="replace")
            if marker not in existing:
                raise GitLabError(
                    "existing pre-push hook is not managed by Koba; refusing to overwrite it"
                )

        credential_file.write_text(self._credential_url(raw_project) + "\n", encoding="utf-8")
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
            '    *" $branch "*) echo "push to bridge-reserved branch denied: $branch" >&2; '
            "exit 1 ;;\n"
            "  esac\n"
            "done\n",
            encoding="utf-8",
        )
        hook.chmod(0o700)

        signature = self._git_signature()
        helper = f"store --file={credential_file}"
        self._git_output(target, "config", "--local", "user.name", signature["name"])
        self._git_output(target, "config", "--local", "user.email", signature["email"])
        self._git_output(target, "config", "--local", f"remote.{remote}.url", expected)
        self._git_output(target, "config", "--local", "credential.helper", helper)
        self._git_output(target, "config", "--local", "credential.useHttpPath", "true")
        self._git_output(target, "config", "--local", "koba.gitlab.project", raw_project)
        self._git_output(
            target,
            "config",
            "--local",
            "koba.gitlab.accountId",
            self.profile.profile_id,
        )
        self._git_output(
            target,
            "config",
            "--local",
            "koba.gitlab.transportAuthorized",
            "true",
        )
        branch = self._git_output(target, "branch", "--show-current")
        return {
            "authorized": True,
            "project": raw_project,
            "workspace": target.relative_to(self.workspace_root.resolve(strict=False)).as_posix(),
            "remote": remote,
            "remote_url": expected,
            "branch": branch,
            "account_id": self.profile.profile_id,
            "credential_storage": "git_credential_store",
            "credential_file": credential_file.relative_to(target).as_posix(),
            "push_mode": "ordinary_git",
        }

    def push_local_git(
        self,
        project: str | int,
        destination: str,
        *,
        branch: str = "",
        remote: str = "origin",
        set_upstream: bool = True,
        expected_remote_sha: str = "",
    ) -> JsonObject:
        if self.anonymous_only:
            raise GitLabError("local Git push requires an authenticated GitLab account")
        raw_project = str(project).strip().strip("/")
        if not raw_project:
            raise GitLabError("project is required")
        target = self._local_git_path(destination)
        remote = remote.strip() or "origin"
        marker_project = self._git_optional_output(
            target, "config", "--local", "--get", "koba.gitlab.project"
        )
        marker_account = self._git_optional_output(
            target, "config", "--local", "--get", "koba.gitlab.accountId"
        )
        marker_enabled = self._git_optional_output(
            target, "config", "--local", "--get", "koba.gitlab.transportAuthorized"
        )
        if (
            marker_project != raw_project
            or marker_account != self.profile.profile_id
            or marker_enabled.casefold() != "true"
        ):
            raise GitLabError(
                "workspace is not authorized for this GitLab account/project; "
                "call authorize_local_git first"
            )

        current_branch = self._git_output(target, "branch", "--show-current")
        push_branch = (branch.strip() or current_branch).strip()
        if not push_branch:
            raise GitLabError("cannot push a detached HEAD; specify a local branch")
        push_branch = require_mutable_branch(push_branch, self.protected_branches)

        expected_sha = expected_remote_sha.strip().casefold()
        if expected_sha and (
            len(expected_sha) != 40
            or any(ch not in "0123456789abcdef" for ch in expected_sha)
        ):
            raise GitLabError("expected_remote_sha must be a 40-character hexadecimal commit SHA")

        args = ["push", "--porcelain"]
        if set_upstream:
            args.append("--set-upstream")
        if expected_sha:
            args.append(
                f"--force-with-lease=refs/heads/{push_branch}:{expected_sha}"
            )
        args += [remote, f"HEAD:refs/heads/{push_branch}"]
        output = self._git_output(target, *args)
        head = self._git_output(target, "rev-parse", "HEAD")
        return {
            "pushed": True,
            "project": raw_project,
            "workspace": target.relative_to(self.workspace_root.resolve(strict=False)).as_posix(),
            "remote": remote,
            "branch": push_branch,
            "head": head,
            "account_id": self.profile.profile_id,
            "force_with_lease": bool(expected_sha),
            "expected_remote_sha": expected_sha or None,
            "git_output": output[-2048:],
        }

    def get_file(self, project: str | int, path: str, ref: str = "main") -> JsonObject:
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/files/{file_path}",
            query={"ref": ref},
        )
        data = response.data
        if not isinstance(data, dict):
            raise GitLabError("unexpected GitLab repository file response")
        encoding = str(data.get("encoding", ""))
        content = str(data.get("content", ""))
        if encoding != "base64":
            raise GitLabError(f"unsupported GitLab repository file encoding: {encoding}")
        decoded = base64.b64decode(content).decode("utf-8", "replace")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "path": data.get("file_path", path),
            "ref": ref,
            "blob_id": data.get("blob_id"),
            "commit_id": data.get("commit_id"),
            "last_commit_id": data.get("last_commit_id"),
            "size": data.get("size"),
            "content": decoded,
        }

    def list_tree(
        self,
        project: str | int,
        path: str = "",
        ref: str = "main",
        recursive: bool = False,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/tree",
            query={
                "path": path or None,
                "ref": ref,
                "recursive": recursive,
                "page": page,
                "per_page": per_page,
            },
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab repository tree response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "items": response.data,
            "page": page,
            "per_page": per_page,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def search_code(
        self,
        project: str | int,
        search: str,
        ref: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        query: JsonObject = {
            "scope": "blobs",
            "search": search,
            "page": page,
            "per_page": per_page,
        }
        if ref:
            query["ref"] = ref
        response = self.request("GET", f"/projects/{selector}/search", query=query)
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab code search response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "results": response.data,
            "page": page,
            "per_page": per_page,
            "next_page": response.headers.get("X-Next-Page", ""),
        }


    def list_commits(
        self,
        project: str | int,
        ref: str = "",
        path: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/commits",
            query={
                "ref_name": ref or None,
                "path": path or None,
                "page": page,
                "per_page": per_page,
            },
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab commit list response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "commits": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def get_commit(
        self,
        project: str | int,
        sha: str,
    ) -> JsonObject:
        selector = self.project_selector(project)
        commit = self.request(
            "GET",
            f"/projects/{selector}/repository/commits/{urllib.parse.quote(sha, safe='')}",
        ).data
        diff = self.request(
            "GET",
            f"/projects/{selector}/repository/commits/{urllib.parse.quote(sha, safe='')}/diff",
        ).data
        if not isinstance(diff, list):
            raise GitLabError("unexpected GitLab commit diff response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "commit": commit,
            "diff": diff,
        }

    def put_file(
        self,
        project: str | int,
        path: str,
        content: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        existing = self.request(
            "GET",
            f"/projects/{selector}/repository/files/{file_path}",
            query={"ref": branch},
            allowed_errors={404},
        )
        method = "POST" if existing.status == 404 else "PUT"
        payload: JsonObject = {
            "branch": branch,
            "content": content,
            "commit_message": commit_message,
        }
        if last_commit_id:
            payload["last_commit_id"] = last_commit_id
        response = self.request(
            method,
            f"/projects/{selector}/repository/files/{file_path}",
            payload=payload,
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "path": path,
            "branch": branch,
            "operation": "create" if method == "POST" else "update",
            "result": response.data,
        }

    def delete_file(
        self,
        project: str | int,
        path: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        payload: JsonObject = {
            "branch": branch,
            "commit_message": commit_message,
        }
        if last_commit_id:
            payload["last_commit_id"] = last_commit_id
        response = self.request(
            "DELETE",
            f"/projects/{selector}/repository/files/{file_path}",
            payload=payload,
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "path": path,
            "branch": branch,
            "result": response.data,
        }

    def commit_actions(
        self,
        project: str | int,
        branch: str,
        commit_message: str,
        actions: list[GitLabCommitAction],
        start_branch: str = "",
    ) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        if not actions:
            raise GitLabError("actions must not be empty")
        clean_actions = [action.to_json() for action in actions]
        selector = self.project_selector(project)
        payload = json_object(
            {
                "branch": branch,
                "commit_message": commit_message,
                "actions": clean_actions,
            },
            context="GitLab commit payload",
        )
        if start_branch:
            payload["start_branch"] = start_branch
        response = self.request(
            "POST",
            f"/projects/{selector}/repository/commits",
            payload=payload,
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branch": branch,
            "commit": response.data,
        }

    def list_branches(
        self,
        project: str | int,
        search: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/branches",
            query={"search": search or None, "page": page, "per_page": per_page},
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab branch list response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branches": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def create_branch(
        self,
        project: str | int,
        branch: str,
        ref: str,
    ) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        response = self.request(
            "POST",
            f"/projects/{selector}/repository/branches",
            query={"branch": branch, "ref": ref},
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branch": response.data,
        }

    def delete_branch(self, project: str | int, branch: str) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        branch_q = urllib.parse.quote(branch, safe="")
        response = self.request(
            "DELETE",
            f"/projects/{selector}/repository/branches/{branch_q}",
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branch": branch,
            "status": response.status,
            "deleted": True,
        }

    def compare(
        self,
        project: str | int,
        from_ref: str,
        to_ref: str,
        straight: bool = False,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/compare",
            query={"from": from_ref, "to": to_ref, "straight": straight},
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "comparison": response.data,
        }
