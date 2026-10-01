from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from common.account_contracts import AccountList, AccountPublic, ResolvedAccount
from common.settings import GitLabSettings
from modules.gitlab.gitlab_client import GitLabClient, GitLabError, GitLabProfile
from modules.gitlab.tool_context import GitLabRuntimeContext


class _GitLabHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *args):
        return

    def _identity(self) -> str:
        token = self.headers.get("PRIVATE-TOKEN", "")
        return {"token-a": "alice", "token-b": "bob"}.get(token, "")

    def _json(self, status: int, payload: object) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/v4/user":
            username = self._identity()
            if not username:
                self._json(401, {"message": "Unauthorized"})
                return
            self._json(
                200,
                {
                    "id": 1 if username == "alice" else 2,
                    "username": username,
                    "name": username.title(),
                    "state": "active",
                    "web_url": f"http://gitlab.test/{username}",
                },
            )
            return
        if path == "/api/v4/version":
            self._json(200, {"version": "18.4.0"})
            return
        if path == "/api/v4/projects":
            self._json(200, [{"id": 123, "path_with_namespace": "group/project"}])
            return
        if path == "/api/v4/personal_access_tokens/self":
            if not self._identity():
                self._json(401, {"message": "Unauthorized"})
                return
            self._json(
                200,
                {
                    "id": 10,
                    "active": True,
                    "scopes": ["api", "read_repository"],
                    "expires_at": None,
                },
            )
            return
        if path == "/api/v4/projects/public%2Frepo":
            if self.headers.get("PRIVATE-TOKEN"):
                self._json(404, {"message": "not found through token"})
                return
            self._json(
                200,
                {
                    "id": 456,
                    "path_with_namespace": "public/repo",
                    "visibility": "public",
                },
            )
            return
        if path == "/api/v4/projects/group%2Fproject":
            self._json(
                200,
                {
                    "id": 123,
                    "path_with_namespace": "group/project",
                    "visibility": "private",
                    "permissions": {
                        "project_access": {"access_level": 40},
                        "group_access": {"access_level": 30},
                    },
                },
            )
            return
        if path == "/api/v4/projects/group%2Fproject/repository/commits":
            self._json(200, [{"id": "abc", "title": "test commit"}])
            return
        if path == "/api/v4/projects/group%2Fproject/repository/commits/abc":
            self._json(200, {"id": "abc", "title": "test commit"})
            return
        if path == "/api/v4/projects/group%2Fproject/repository/commits/abc/diff":
            self._json(200, [{"old_path": "a.py", "new_path": "a.py", "diff": "@@ test"}])
            return
        if path == "/api/v4/projects/group%2Fproject/merge_requests/7/diffs":
            self._json(200, [{"old_path": "a.py", "new_path": "a.py", "diff": "@@ mr"}])
            return
        self._json(404, {"message": "not found", "path": path})


    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/v4/projects/group%2Fproject/merge_requests/7/notes":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            self._json(201, {"id": 99, "body": payload.get("body", "")})
            return
        self._json(404, {"message": "not found", "path": path})


@pytest.fixture(scope="module")
def gitlab_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GitLabHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _profile(account_id: str, alias: str, url: str, token: str) -> GitLabProfile:
    profile = GitLabProfile(
        account_id=account_id,
        alias=alias,
        base_url=url,
        auth_type="private_token",
    )
    profile.bind_token(token)
    return profile


def test_two_accounts_same_self_hosted_instance_are_isolated(gitlab_server: str) -> None:
    alice = GitLabClient(_profile("a", "alice", gitlab_server, "token-a")).profile_status()
    bob = GitLabClient(_profile("b", "bob", gitlab_server, "token-b")).profile_status()

    assert alice["authenticated_user"]["username"] == "alice"
    assert bob["authenticated_user"]["username"] == "bob"
    assert alice["account"]["base_url"] == bob["account"]["base_url"]


def test_self_hosted_url_prefix_is_preserved() -> None:
    client = GitLabClient(
        _profile(
            "a",
            "prefix",
            "https://gitlab.example.test/platform",
            "token-a",
        )
    )
    assert client._target("/user") == "/platform/api/v4/user"


def test_protected_branch_policy_is_injected(gitlab_server: str) -> None:
    client = GitLabClient(
        _profile("a", "alice", gitlab_server, "token-a"),
        protected_branches=frozenset({"main"}),
    )
    with pytest.raises(GitLabError, match="protected branch"):
        client.put_file("group/project", "README.md", "x", "main", "blocked")


class _FakeControlPlane:
    def __init__(self, accounts: dict[str, ResolvedAccount]) -> None:
        self.accounts = accounts
        self.resolve_calls = 0

    def list_accounts(self, *, provider=None):
        public = [
            AccountPublic.model_validate(account.model_dump(exclude={"credential"}))
            for account in self.accounts.values()
            if provider is None or account.provider == provider
        ]
        return AccountList(accounts=public, count=len(public))

    def resolve_account(self, selector: str, *, provider: str):
        self.resolve_calls += 1
        account = self.accounts[selector]
        assert account.provider == provider
        return account


def test_runtime_context_caches_by_account_version(gitlab_server: str) -> None:
    account = ResolvedAccount(
        id="acc",
        alias="local",
        provider="gitlab",
        auth_type="private_token",
        base_url=gitlab_server,
        external_id=None,
        verify_tls=True,
        ca_cert_pem=None,
        enabled=True,
        created_at="2026-09-23T00:00:00+00:00",
        updated_at="2026-09-23T00:00:00+00:00",
        credential="token-a",
    )
    control = _FakeControlPlane({"local": account})
    context = GitLabRuntimeContext(control, GitLabSettings())

    first = context.client("local")
    second = context.client("local")

    assert first is second
    assert control.resolve_calls == 2

    control.accounts["local"] = account.model_copy(
        update={
            "updated_at": "2026-09-23T01:00:00+00:00",
            "credential": "token-b",
        }
    )
    third = context.client("local")
    assert third is not first


def test_gitlab_account_capabilities_report_pat_scopes_and_project_access(
    gitlab_server: str,
) -> None:
    client = GitLabClient(_profile("a", "alice", gitlab_server, "token-a"))

    result = client.account_capabilities("group/project")

    assert result["provider_permissions_known"] is True
    assert result["provider_permissions"]["scopes"] == ["api", "read_repository"]
    assert result["project"]["access"]["project_access"] == {
        "access_level": 40,
        "access_level_name": "maintainer",
    }


def test_gitlab_account_list_exposes_potential_capabilities(gitlab_server: str) -> None:
    account = ResolvedAccount(
        id="acc",
        alias="local",
        provider="gitlab",
        auth_type="private_token",
        base_url=gitlab_server,
        external_id=None,
        verify_tls=True,
        ca_cert_pem=None,
        enabled=True,
        created_at="2026-09-23T00:00:00+00:00",
        updated_at="2026-09-23T00:00:00+00:00",
        credential="token-a",
    )
    context = GitLabRuntimeContext(_FakeControlPlane({"local": account}), GitLabSettings())

    result = context.accounts()

    listed = result["accounts"][0]
    assert listed["permission_scope"] == "project-dependent"
    assert listed["preferred_selector"] == "local"
    assert listed["selector_stability"] == "stable_alias"
    assert "personal_access_token_scoped_access" in listed["potential_capabilities"]


def test_gitlab_single_account_commit_and_merge_request_review_helpers(
    gitlab_server: str,
) -> None:
    client = GitLabClient(_profile("a", "alice", gitlab_server, "token-a"))

    commits = client.list_commits("group/project")
    commit = client.get_commit("group/project", "abc")
    diffs = client.list_merge_request_diffs("group/project", 7)
    note = client.add_merge_request_note("group/project", 7, "reviewed")

    assert commits["commits"][0]["id"] == "abc"
    assert commit["commit"]["id"] == "abc"
    assert commit["diff"][0]["new_path"] == "a.py"
    assert diffs["diffs"][0]["diff"] == "@@ mr"
    assert note["note"]["body"] == "reviewed"


def test_gitlab_merge_request_note_rejects_empty_body(gitlab_server: str) -> None:
    client = GitLabClient(_profile("a", "alice", gitlab_server, "token-a"))

    with pytest.raises(GitLabError, match="note body is required"):
        client.add_merge_request_note("group/project", 7, "   ")


def test_gitlab_get_retries_anonymously_for_public_project(
    gitlab_server: str,
) -> None:
    client = GitLabClient(_profile("a", "alice", gitlab_server, "token-a"))

    response = client.request("GET", "/projects/public%2Frepo")

    assert response.status == 200
    assert response.data["path_with_namespace"] == "public/repo"


def test_gitlab_mutation_does_not_retry_anonymously(
    gitlab_server: str,
) -> None:
    client = GitLabClient(_profile("a", "alice", gitlab_server, "token-a"))

    with pytest.raises(GitLabError):
        client.request(
            "POST",
            "/projects/public%2Frepo/issues",
            payload={"title": "blocked"},
        )
