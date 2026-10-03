import base64
import time

import pytest

from common.http_transport import HttpTransportResponse
from modules.github.github_agent import (
    GitHubAgentError,
    GitHubAppClient,
)


def test_repository_selector_only_validates_owner_name_shape() -> None:
    client = GitHubAppClient(app_id="123", private_key="key")

    assert client._assert_allowed("ArthurKoba/mcp-bridge") == ("ArthurKoba/mcp-bridge")
    assert client._assert_allowed("someone/else") == "someone/else"

    for invalid in ("", "owner", "/repo", "owner/", "owner/repo/extra"):
        with pytest.raises(GitHubAgentError, match="owner/name"):
            client._assert_allowed(invalid)


class RecordingInstallationClient(GitHubAppClient):
    def _app_jwt(self) -> str:
        return "app-jwt"

    def _request(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
        auth_mode: str = "",
    ) -> tuple[int, object]:
        del payload, allowed_errors, auth_mode
        if method == "GET" and url.endswith("/app/installations?per_page=100&page=1"):
            assert token == "app-jwt"
            return 200, [{"id": 99}]
        if method == "POST" and url.endswith("/app/installations/99/access_tokens"):
            assert token == "app-jwt"
            return 201, {
                "token": "installation-token",
                "expires_at": "2099-01-01T00:00:00Z",
            }
        if method == "GET" and url.endswith("/installation/repositories?per_page=100&page=1"):
            assert token == "installation-token"
            return 200, {
                "total_count": 2,
                "repositories": [
                    {
                        "full_name": "ArthurKoba/mcp-bridge",
                        "private": False,
                        "default_branch": "main",
                        "archived": False,
                        "fork": False,
                        "permissions": {"push": True, "pull": True},
                    },
                    {
                        "full_name": "ArthurKoba/ghidra-mcp",
                        "private": False,
                        "default_branch": "main",
                        "archived": False,
                        "fork": False,
                        "permissions": {"push": True, "pull": True},
                    },
                ],
            }
        raise AssertionError(f"unexpected request: {method} {url}")


def test_list_repositories_uses_github_installation_scope() -> None:
    client = RecordingInstallationClient(app_id="123", private_key="key")
    result = client.list_repositories()

    assert result["app_id"] == "123"
    assert result["count"] == 2
    assert [repo["full_name"] for repo in result["repositories"]] == [
        "ArthurKoba/ghidra-mcp",
        "ArthurKoba/mcp-bridge",
    ]
    assert client._installation_ids["arthurkoba/ghidra-mcp"] == 99
    assert client._installation_ids["arthurkoba/mcp-bridge"] == 99


def test_app_id_must_be_positive_numeric() -> None:
    client = GitHubAppClient(app_id="not-an-id", private_key="unused")
    with pytest.raises(GitHubAgentError, match="positive numeric"):
        client._app_jwt()


def test_invalid_private_key_reports_actionable_error() -> None:
    client = GitHubAppClient(app_id="123", private_key="not-a-pem")
    with pytest.raises(GitHubAgentError, match=r"PRIVATE_KEY_PEM.*RSA private key"):
        client._app_jwt()


def test_github_401_diagnostics_distinguish_app_and_installation_auth() -> None:
    app_message = GitHubAppClient._github_error_message(
        401,
        "https://api.github.com/app",
        b'{"message":"Bad credentials"}',
    )
    installation_message = GitHubAppClient._github_error_message(
        401,
        "https://api.github.com/repos/owner/repo",
        b'{"message":"Bad credentials"}',
    )

    assert "APP_ID" in app_message
    assert "PRIVATE_KEY_PEM" in app_message
    assert "installation token" in installation_message


def test_github_403_diagnostic_mentions_permissions() -> None:
    message = GitHubAppClient._github_error_message(
        403,
        "https://api.github.com/repos/owner/repo/actions/runs",
        b'{"message":"Resource not accessible by integration"}',
    )
    assert "permissions" in message
    assert "HTTP 403" in message


def test_missing_installation_has_actionable_error() -> None:
    class MissingInstallationClient(GitHubAppClient):
        def _app_jwt(self) -> str:
            return "app-jwt"

        def _request(
            self,
            method: str,
            url: str,
            *,
            token: str | None = None,
            payload: object | None = None,
            allowed_errors: set[int] | None = None,
            auth_mode: str = "",
        ) -> tuple[int, object]:
            del method, url, token, payload, allowed_errors, auth_mode
            return 404, {"message": "Not Found"}

    client = MissingInstallationClient(app_id="123", private_key="unused")
    with pytest.raises(GitHubAgentError, match=r"not installed.*add it"):
        client._installation_id("owner/repo")


def test_repository_metadata_is_cached_until_refresh() -> None:
    class MetadataClient(GitHubAppClient):
        def __init__(self) -> None:
            super().__init__(
                app_id="123",
                private_key="unused",
                repository_cache_ttl_seconds=60,
            )
            self.calls = 0
            self._installation_ids["owner/repo"] = 7

        def _repo_request(
            self,
            repository: str,
            method: str,
            path: str,
            *,
            payload: object | None = None,
            allowed_errors: set[int] | None = None,
            auth_mode: str = "",
        ) -> tuple[int, object]:
            del repository, method, path, payload, allowed_errors
            self.calls += 1
            return 200, {
                "full_name": "owner/repo",
                "default_branch": "main",
                "private": False,
                "archived": False,
                "fork": False,
            }

    client = MetadataClient()
    first = client.status("owner/repo")
    second = client.status("owner/repo")

    assert first == second
    assert client.calls == 1

    refreshed = client._repository_metadata("owner/repo", refresh=True)
    assert refreshed["repository"] == "owner/repo"
    assert client.calls == 2


def test_app_get_does_not_fall_back_to_anonymous_when_not_installed() -> None:
    class MissingInstallationClient(GitHubAppClient):
        def _installation_token(self, repository: str) -> str:
            raise GitHubAgentError(f"repository {repository!r} is not installed for GitHub App 123")

        def _request(self, *args, **kwargs):
            raise AssertionError("anonymous GitHub request must not be attempted")

    client = MissingInstallationClient(app_id="123", private_key="unused")

    with pytest.raises(GitHubAgentError, match="account_id='public'"):
        client._repository_metadata("public/repo")


def test_public_fallback_never_applies_to_mutations() -> None:
    class PublicFallbackClient(GitHubAppClient):
        def _installation_token(self, repository: str) -> str:
            raise GitHubAgentError(f"repository {repository!r} is not installed for GitHub App 123")

    client = PublicFallbackClient(app_id="123", private_key="unused")
    with pytest.raises(GitHubAgentError, match="not installed"):
        client._repo_request(
            "public/repo",
            "POST",
            "/repos/public/repo/issues",
            payload={"title": "no"},
        )


def test_authenticated_public_reader_uses_token_but_remains_read_only() -> None:
    class PublicReaderClient(GitHubAppClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.calls: list[tuple[str, str, str | None, str]] = []

        def _request(
            self,
            method: str,
            url: str,
            *,
            token: str | None = None,
            payload: object | None = None,
            allowed_errors: set[int] | None = None,
            auth_mode: str = "",
        ) -> tuple[int, object]:
            del payload, allowed_errors
            self.calls.append((method, url, token, auth_mode))
            return 200, {
                "full_name": "octocat/Hello-World",
                "default_branch": "master",
                "private": False,
                "archived": False,
                "fork": False,
            }

    client = PublicReaderClient(
        account_id="public",
        auth_type="public",
        public_only=True,
        token="reader-token",
        public_reader_account="authenticated",
    )

    metadata = client._repository_metadata("octocat/Hello-World")

    assert metadata["repository"] == "octocat/Hello-World"
    assert client.calls == [
        (
            "GET",
            "https://api.github.com/repos/octocat/Hello-World",
            "reader-token",
            "public_reader",
        )
    ]
    with pytest.raises(GitHubAgentError, match="read-only"):
        client._repo_request(
            "octocat/Hello-World",
            "POST",
            "/repos/octocat/Hello-World/issues",
            payload={"title": "must not write"},
        )
    assert len(client.calls) == 1


def test_invalid_app_auth_does_not_silently_fallback() -> None:
    class BrokenAppClient(GitHubAppClient):
        def _installation_token(self, repository: str) -> str:
            del repository
            raise GitHubAgentError("GitHub App authentication failed (HTTP 401)")

    client = BrokenAppClient(app_id="123", private_key="unused")
    with pytest.raises(GitHubAgentError, match="authentication failed"):
        client._repo_request("public/repo", "GET", "/repos/public/repo")


def test_public_github_checkout_skips_installation_auth(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_checkout(clone_url, destination, **kwargs):
        captured["clone_url"] = clone_url
        captured["destination"] = destination
        captured.update(kwargs)
        return {
            "path": destination,
            "mode": kwargs["mode"],
            "ref": kwargs["ref"],
            "git_metadata": False,
            "auth_mode": "anonymous",
        }

    monkeypatch.setattr(
        "modules.github.github_agent.checkout_repository",
        fake_checkout,
    )
    client = GitHubAppClient(
        account_id="public",
        auth_type="public",
        public_only=True,
    )

    result = client.checkout_repository(
        "octocat/Hello-World",
        "repos/hello",
    )

    assert result["repository"] == "octocat/Hello-World"
    assert captured["auth_header"] == ""


def test_authenticated_public_checkout_uses_reader_credentials(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_checkout(clone_url, destination, **kwargs):
        captured.update(kwargs)
        return {
            "path": destination,
            "mode": kwargs["mode"],
            "ref": kwargs["ref"],
            "git_metadata": True,
            "auth_mode": "authenticated",
        }

    monkeypatch.setattr("modules.github.github_agent.checkout_repository", fake_checkout)
    client = GitHubAppClient(
        account_id="public",
        auth_type="public",
        public_only=True,
        token="reader-token",
    )

    client.checkout_repository("octocat/Hello-World", "repos/hello", mode="git")

    expected = base64.b64encode(b"x-access-token:reader-token").decode("ascii")
    assert captured["auth_header"] == f"Authorization: Basic {expected}"


def test_authenticated_github_checkout_uses_basic_git_credentials(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_checkout(clone_url, destination, **kwargs):
        captured["clone_url"] = clone_url
        captured["destination"] = destination
        captured.update(kwargs)
        return {
            "path": destination,
            "mode": kwargs["mode"],
            "ref": kwargs["ref"],
            "git_metadata": True,
            "auth_mode": "authenticated",
        }

    monkeypatch.setattr(
        "modules.github.github_agent.checkout_repository",
        fake_checkout,
    )
    client = GitHubAppClient(token="installation-token")

    client.checkout_repository("ArthurKoba/mcp-bridge", "repos/bridge", mode="git")

    expected = base64.b64encode(b"x-access-token:installation-token").decode("ascii")
    assert captured["auth_header"] == f"Authorization: Basic {expected}"


def test_rate_limit_headers_are_recorded_and_exposed() -> None:
    client = GitHubAppClient(token="user-token", auth_type="github_token")
    reset = int(time.time()) + 600

    class FakeTransport:
        def request(self, method, target, **kwargs):
            del method, target, kwargs
            return HttpTransportResponse(
                status=200,
                headers={
                    "X-RateLimit-Limit": "5000",
                    "X-RateLimit-Remaining": "4321",
                    "X-RateLimit-Used": "679",
                    "X-RateLimit-Reset": str(reset),
                    "X-RateLimit-Resource": "core",
                },
                body=b'{"ok":true}',
                will_close=False,
            )

    client._transport = FakeTransport()  # type: ignore[assignment]
    client._request(
        "GET",
        "https://api.github.com/rate_limit",
        token="user-token",
        auth_mode="user_token",
    )

    status = client.rate_limit_status()
    entry = status["entries"][0]
    assert entry["auth_mode"] == "user_token"
    assert entry["resource"] == "core"
    assert entry["limit"] == 5000
    assert entry["remaining"] == 4321
    assert entry["used"] == 679
    assert entry["reset_epoch"] == reset


def test_rate_limit_error_includes_bucket_reset_and_retry_after() -> None:
    client = GitHubAppClient(token="user-token", auth_type="github_token")
    reset = int(time.time()) + 60

    class FakeTransport:
        def request(self, method, target, **kwargs):
            del method, target, kwargs
            return HttpTransportResponse(
                status=403,
                headers={
                    "X-RateLimit-Limit": "5000",
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Used": "5000",
                    "X-RateLimit-Reset": str(reset),
                    "X-RateLimit-Resource": "core",
                    "Retry-After": "60",
                },
                body=b'{"message":"API rate limit exceeded"}',
                will_close=False,
            )

    client._transport = FakeTransport()  # type: ignore[assignment]

    with pytest.raises(GitHubAgentError) as exc_info:
        client._request(
            "GET",
            "https://api.github.com/user",
            token="user-token",
            auth_mode="user_token",
        )

    message = str(exc_info.value)
    assert "rate limit exceeded" in message
    assert "resource=core" in message
    assert "auth_mode=user_token" in message
    assert "remaining=0" in message
    assert "retry_after_seconds=60" in message
