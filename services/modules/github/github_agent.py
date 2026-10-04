from __future__ import annotations

import base64
import http.client
import json
import ssl
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import jwt

from common.http_transport import HttpTransportError, PooledHttpTransport
from common.models import (
    JsonContainer,
    JsonObject,
    json_array,
    json_bool,
    json_container,
    json_int,
    json_loads,
    json_member_array,
    json_member_object,
    json_object,
    json_str,
    json_value,
)
from common.repository_checkout import checkout_repository

_GITHUB_API = "https://api.github.com"
_GITHUB_API_VERSION = "2026-03-10"


class GitHubAgentError(RuntimeError):
    """Raised when the GitHub App backend cannot complete a request."""


@dataclass
class GitHubAppClient:
    app_id: str = ""
    private_key: str = ""
    account_id: str = ""
    token: str = ""
    auth_type: str = "github_app"
    public_only: bool = False
    _installation_ids: dict[str, int] = field(default_factory=dict)
    _tokens: dict[int, tuple[str, float]] = field(default_factory=dict)
    repository_cache_ttl_seconds: float = 30.0
    max_connections: int = 8
    workspace_root: Path = Path("/workspace")
    protected_branches: frozenset[str] = frozenset({"main", "master"})
    required_checks: tuple[str, ...] = ("test", "docker")
    required_reviewers: tuple[str, ...] = ()
    _transport: PooledHttpTransport = field(init=False, repr=False)
    _cache_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )
    _credential_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )
    _repository_cache: dict[str, tuple[float, JsonObject]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    public_reader_account: str = ""
    _rate_limit_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )
    _rate_limits: dict[str, JsonObject] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self._transport = PooledHttpTransport(
            lambda: http.client.HTTPSConnection(
                "api.github.com",
                timeout=30,
                context=ssl.create_default_context(),
            ),
            max_connections=self.max_connections,
            acquire_timeout=30,
            span_name="provider.github.http",
            provider="github",
        )

    def _assert_allowed(self, repository: str) -> str:
        """Validate a repository selector; GitHub installation scope is the access policy."""
        repository = repository.strip()
        owner, separator, name = repository.partition("/")
        if separator != "/" or not owner or not name or "/" in name:
            raise GitHubAgentError("repository must be owner/name")
        return repository

    def _app_jwt(self) -> str:
        app_id = self.app_id.strip()
        if not app_id.isdigit() or int(app_id) <= 0:
            raise GitHubAgentError(
                f"GitHub APP_ID must be a positive numeric App ID; got {app_id!r}"
            )

        now = int(time.time())
        try:
            token = jwt.encode(
                {
                    "iat": now - 60,
                    "exp": now + 9 * 60,
                    "iss": app_id,
                },
                self.private_key,
                algorithm="RS256",
            )
        except Exception as exc:
            raise GitHubAgentError(
                "GitHub App PRIVATE_KEY_PEM is not a usable RSA private key; "
                "check that the PEM belongs to the configured APP_ID and was not "
                "stored as base64 or truncated text"
            ) from exc
        return str(token)

    @staticmethod
    def _decode_json(data: bytes) -> JsonContainer:
        if not data:
            return {}
        try:
            return json_container(
                json_loads(data, context="GitHub response"),
                context="GitHub response",
            )
        except ValueError as exc:
            raise GitHubAgentError("GitHub returned invalid JSON") from exc

    @staticmethod
    def _request_target(url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise GitHubAgentError("GitHub API request must target https://api.github.com")
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        return target

    @staticmethod
    def _header_int(headers: dict[str, str], name: str) -> int | None:
        raw = headers.get(name)
        if raw is None or not raw.strip():
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _record_rate_limit(
        self,
        headers: dict[str, str],
        *,
        status: int,
        auth_mode: str,
    ) -> JsonObject:
        normalized = {key.casefold(): value for key, value in headers.items()}
        resource = normalized.get("x-ratelimit-resource", "core").strip() or "core"
        limit = self._header_int(normalized, "x-ratelimit-limit")
        remaining = self._header_int(normalized, "x-ratelimit-remaining")
        used = self._header_int(normalized, "x-ratelimit-used")
        reset_epoch = self._header_int(normalized, "x-ratelimit-reset")
        retry_after = self._header_int(normalized, "retry-after")
        if all(value is None for value in (limit, remaining, used, reset_epoch, retry_after)):
            return {}
        now = int(time.time())
        reset_at = ""
        reset_in_seconds: int | None = None
        if reset_epoch is not None:
            reset_at = datetime.fromtimestamp(reset_epoch, tz=UTC).isoformat()
            reset_in_seconds = max(0, reset_epoch - now)
        snapshot: JsonObject = {
            "resource": resource,
            "auth_mode": auth_mode,
            "http_status": status,
            "limit": limit,
            "remaining": remaining,
            "used": used,
            "reset_epoch": reset_epoch,
            "reset_at": reset_at,
            "reset_in_seconds": reset_in_seconds,
            "retry_after_seconds": retry_after,
            "observed_at": datetime.now(tz=UTC).isoformat(),
        }
        with self._rate_limit_lock:
            self._rate_limits[f"{auth_mode}:{resource}"] = dict(snapshot)
        return snapshot

    def rate_limit_status(self) -> JsonObject:
        with self._rate_limit_lock:
            entries = [dict(item) for item in self._rate_limits.values()]
        entries.sort(
            key=lambda item: (
                str(item.get("auth_mode", "")),
                str(item.get("resource", "")),
            )
        )
        return {
            "auth_type": self.auth_type,
            "public_only": self.public_only,
            "public_reader_account": self.public_reader_account,
            "entries": json_array(entries, context="GitHub rate limit entries"),
        }

    @staticmethod
    def _rate_limit_error_message(rate_limit: JsonObject) -> str:
        resource = str(rate_limit.get("resource") or "core")
        auth_mode = str(rate_limit.get("auth_mode") or "unknown")
        remaining = rate_limit.get("remaining")
        reset_at = str(rate_limit.get("reset_at") or "")
        retry_after = rate_limit.get("retry_after_seconds")
        pieces = [
            f"resource={resource}",
            f"auth_mode={auth_mode}",
            f"remaining={remaining if remaining is not None else 'unknown'}",
        ]
        if reset_at:
            pieces.append(f"reset_at={reset_at}")
        if retry_after is not None:
            pieces.append(f"retry_after_seconds={retry_after}")
        return ", ".join(pieces)

    @classmethod
    def _github_error_message(
        cls,
        status: int,
        url: str,
        data: bytes,
        rate_limit: JsonObject | None = None,
    ) -> str:
        detail = data[:4096].decode("utf-8", "replace")
        path = urllib.parse.urlsplit(url).path
        rate = rate_limit or {}
        rate_text = cls._rate_limit_error_message(rate) if rate else ""
        detail_casefold = detail.casefold()
        if status == 401:
            if (
                path == "/app"
                or path.endswith("/installation")
                or (path.startswith("/app/installations/") and path.endswith("/access_tokens"))
            ):
                return (
                    "GitHub App authentication failed (HTTP 401); check that APP_ID "
                    "matches PRIVATE_KEY_PEM and that the GitHub App private key is active"
                )
            return (
                "GitHub installation authentication failed (HTTP 401); the installation "
                "token may be expired/revoked or the App installation may have changed"
            )
        if status in {403, 429} and (
            rate.get("remaining") == 0
            or rate.get("retry_after_seconds") is not None
            or "rate limit" in detail_casefold
        ):
            suffix = f" ({rate_text})" if rate_text else ""
            return f"GitHub API rate limit exceeded (HTTP {status}) for {path}{suffix}: {detail}"
        if status == 403:
            return (
                "GitHub API denied the operation (HTTP 403); check GitHub App repository "
                f"permissions for {path}: {detail}"
            )
        return f"GitHub API HTTP {status}: {detail}"

    def _request(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
        auth_mode: str = "",
    ) -> tuple[int, JsonContainer]:
        body = (
            None
            if payload is None
            else json.dumps(
                json_value(payload, context="GitHub request payload"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "mcp-bridge",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"

        target = self._request_target(url)
        normalized_method = method.upper()
        try:
            response = self._transport.request(
                normalized_method,
                target,
                body=body,
                headers=headers,
                reconnect_retries=6 if normalized_method in {"GET", "HEAD"} else 1,
                retry_backoff_seconds=0.25 if normalized_method in {"GET", "HEAD"} else 0.0,
            )
        except HttpTransportError as exc:
            raise GitHubAgentError(f"GitHub API transport error: {exc}") from exc

        status = response.status
        data = response.body
        effective_auth_mode = auth_mode or ("authenticated" if token else "anonymous")
        rate_limit = self._record_rate_limit(
            response.headers,
            status=status,
            auth_mode=effective_auth_mode,
        )
        if status >= 400:
            if allowed_errors and status in allowed_errors:
                try:
                    parsed = self._decode_json(data)
                except Exception:
                    parsed = {"message": data.decode("utf-8", "replace")}
                return status, parsed
            raise GitHubAgentError(self._github_error_message(status, url, data, rate_limit))

        return status, self._decode_json(data)

    def _installation_id(self, repository: str) -> int:
        repository = self._assert_allowed(repository)
        key = repository.casefold()
        cached = self._installation_ids.get(key)
        if cached is not None:
            return cached

        with self._credential_lock:
            cached = self._installation_ids.get(key)
            if cached is not None:
                return cached
            status, result = self._request(
                "GET",
                f"{_GITHUB_API}/repos/{repository}/installation",
                token=self._app_jwt(),
                allowed_errors={404},
                auth_mode="github_app_jwt",
            )
            if status == 404:
                raise GitHubAgentError(
                    f"repository {repository!r} is not installed for GitHub App "
                    f"{self.app_id}; add it to the App installation or use the correct App"
                )
            try:
                payload = json_object(result, context="GitHub installation response")
                installation_id = json_int(payload.get("id"))
            except ValueError as exc:
                raise GitHubAgentError("GitHub did not return an installation id") from exc
            if installation_id <= 0:
                raise GitHubAgentError("GitHub did not return an installation id")
            self._installation_ids[key] = installation_id
            return installation_id

    def _installation_token_for_id(self, installation_id: int) -> str:
        cached = self._tokens.get(installation_id)
        if cached is not None and cached[1] > time.time() + 120:
            return cached[0]

        with self._credential_lock:
            cached = self._tokens.get(installation_id)
            if cached is not None and cached[1] > time.time() + 120:
                return cached[0]

            _, result = self._request(
                "POST",
                f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
                token=self._app_jwt(),
                auth_mode="github_app_jwt",
            )
            try:
                token_payload = json_object(
                    result,
                    context="GitHub installation token response",
                )
                token = json_str(token_payload.get("token"))
                expires_at = json_str(token_payload.get("expires_at"))
            except ValueError as exc:
                raise GitHubAgentError(
                    "GitHub did not return an installation token payload"
                ) from exc
            if not token or not expires_at:
                raise GitHubAgentError(
                    "GitHub installation token response is incomplete; check App "
                    "installation state and permissions"
                )
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
            except ValueError as exc:
                raise GitHubAgentError(
                    "GitHub installation token response has invalid expires_at"
                ) from exc
            self._tokens[installation_id] = (token, expiry)
            return token

    def _installation_token(self, repository: str) -> str:
        if self.token:
            self._assert_allowed(repository)
            return self.token
        return self._installation_token_for_id(self._installation_id(repository))

    def _any_installation_token(self) -> str:
        now = time.time() + 120
        for _installation_id, cached in list(self._tokens.items()):
            if cached[1] > now:
                return cached[0]
        installation_ids = self._installation_ids_from_github()
        if not installation_ids:
            raise GitHubAgentError(
                "GitHub App has no installations; authenticated App identity lookup is unavailable"
            )
        return self._installation_token_for_id(installation_ids[0])

    def _assert_public_repository(self, repository: str) -> None:
        key = repository.casefold()
        now = time.monotonic()
        if self.repository_cache_ttl_seconds > 0:
            with self._cache_lock:
                cached = self._repository_cache.get(key)
                if cached is not None and cached[0] > now:
                    if bool(cached[1].get("private")):
                        raise GitHubAgentError(
                            "public GitHub access cannot read private repositories"
                        )
                    return
        _, result = self._request(
            "GET",
            f"{_GITHUB_API}/repos/{repository}",
            token=self.token or None,
            auth_mode="public_reader" if self.token else "public_anonymous",
        )
        try:
            payload = json_object(result, context="GitHub repository response")
        except ValueError as exc:
            raise GitHubAgentError("unexpected repository response") from exc
        metadata: JsonObject = {
            "repository": json_str(payload.get("full_name"), default=repository),
            "default_branch": json_str(payload.get("default_branch")),
            "private": json_bool(payload.get("private")),
            "archived": json_bool(payload.get("archived")),
            "fork": json_bool(payload.get("fork")),
        }
        if bool(metadata["private"]):
            raise GitHubAgentError("public GitHub access cannot read private repositories")
        if self.repository_cache_ttl_seconds > 0:
            with self._cache_lock:
                self._repository_cache[key] = (
                    time.monotonic() + self.repository_cache_ttl_seconds,
                    dict(metadata),
                )

    def _repo_request(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, JsonContainer]:
        repository = self._assert_allowed(repository)
        normalized_method = method.upper()
        if self.public_only:
            if normalized_method not in {"GET", "HEAD"}:
                raise GitHubAgentError("public GitHub access is read-only")
            if path.split("?", 1)[0] != f"/repos/{repository}":
                self._assert_public_repository(repository)
            return self._request(
                normalized_method,
                f"{_GITHUB_API}{path}",
                token=self.token or None,
                payload=payload,
                allowed_errors=allowed_errors,
                auth_mode="public_reader" if self.token else "public_anonymous",
            )
        if self.token:
            return self._request(
                normalized_method,
                f"{_GITHUB_API}{path}",
                token=self.token,
                payload=payload,
                allowed_errors=allowed_errors,
                auth_mode="user_token",
            )
        try:
            token = self._installation_token(repository)
        except GitHubAgentError as exc:
            if normalized_method in {"GET", "HEAD"} and "is not installed for GitHub App" in str(
                exc
            ):
                raise GitHubAgentError(
                    f"repository {repository!r} is outside this GitHub App installation; "
                    "use account_id='public' for authenticated read-only public access"
                ) from exc
            raise
        return self._request(
            normalized_method,
            f"{_GITHUB_API}{path}",
            token=token,
            payload=payload,
            allowed_errors=allowed_errors,
            auth_mode="installation",
        )

    @staticmethod
    def _git_authorization_header(token: str) -> str:
        if not token:
            return ""
        encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
        return f"Authorization: Basic {encoded}"

    def checkout_repository(
        self,
        repository: str,
        destination: str,
        *,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        token = ""
        if self.public_only:
            self._assert_public_repository(repository)
        if self.public_only or self.token:
            token = self.token
        else:
            try:
                token = self._installation_token(repository)
            except GitHubAgentError as exc:
                if "is not installed for GitHub App" not in str(exc):
                    raise
        result = checkout_repository(
            f"https://github.com/{repository}.git",
            destination,
            workspace_root=self.workspace_root,
            mode=mode,
            ref=ref,
            overwrite=overwrite,
            auth_scope="https://github.com/",
            auth_header=self._git_authorization_header(token),
            fallback_without_auth=False,
        )
        result["repository"] = repository
        return result

    def _installation_ids_from_github(self) -> list[int]:
        installation_ids: list[int] = []
        page = 1
        while True:
            _, result = self._request(
                "GET",
                f"{_GITHUB_API}/app/installations?per_page=100&page={page}",
                token=self._app_jwt(),
                auth_mode="github_app_jwt",
            )
            if not isinstance(result, list):
                raise GitHubAgentError("unexpected GitHub App installation list response")
            for raw_item in result:
                try:
                    item = json_object(
                        raw_item,
                        context="GitHub App installation item",
                    )
                    installation_id = json_int(item.get("id"))
                except ValueError as exc:
                    raise GitHubAgentError("unexpected GitHub App installation item") from exc
                if installation_id <= 0:
                    raise GitHubAgentError("unexpected GitHub App installation item")
                installation_ids.append(installation_id)
            if len(result) < 100:
                break
            page += 1
        return installation_ids

    def list_repositories(self) -> JsonObject:
        """List repositories available to the configured GitHub identity."""
        if self.token:
            token_repositories: list[JsonObject] = []
            page = 1
            while True:
                _, result = self._request(
                    "GET",
                    (
                        f"{_GITHUB_API}/user/repos?"
                        "affiliation=owner,collaborator,organization_member"
                        f"&per_page=100&page={page}"
                    ),
                    token=self.token,
                    auth_mode="user_token",
                )
                if not isinstance(result, list):
                    raise GitHubAgentError("unexpected GitHub repository list response")
                for raw_item in result:
                    item = json_object(raw_item, context="GitHub repository item")
                    full_name = json_str(item.get("full_name"))
                    if not full_name:
                        continue
                    token_repositories.append(
                        {
                            "full_name": full_name,
                            "private": json_bool(item.get("private")),
                            "default_branch": json_str(item.get("default_branch")),
                            "archived": json_bool(item.get("archived")),
                            "fork": json_bool(item.get("fork")),
                            "permissions": json_member_object(item, "permissions"),
                        }
                    )
                if len(result) < 100:
                    break
                page += 1
            token_repositories.sort(key=lambda item: str(item["full_name"]).casefold())
            return {
                "auth_type": self.auth_type,
                "count": len(token_repositories),
                "repositories": json_array(
                    token_repositories,
                    context="GitHub token repositories",
                ),
            }

        app_repositories: list[JsonObject] = []
        seen: set[str] = set()
        for installation_id in self._installation_ids_from_github():
            token = self._installation_token_for_id(installation_id)
            page = 1
            while True:
                _, result = self._request(
                    "GET",
                    f"{_GITHUB_API}/installation/repositories?per_page=100&page={page}",
                    token=token,
                    auth_mode="installation",
                )
                response = json_object(result, context="GitHub installation repository response")
                items = json_member_array(response, "repositories", required=True)
                for raw_item in items:
                    item = json_object(raw_item, context="GitHub installation repository item")
                    full_name = json_str(item.get("full_name"))
                    if not full_name or full_name.casefold() in seen:
                        continue
                    seen.add(full_name.casefold())
                    self._installation_ids[full_name.casefold()] = installation_id
                    app_repositories.append(
                        {
                            "full_name": full_name,
                            "private": json_bool(item.get("private")),
                            "default_branch": json_str(item.get("default_branch")),
                            "archived": json_bool(item.get("archived")),
                            "fork": json_bool(item.get("fork")),
                            "permissions": json_member_object(item, "permissions"),
                            "installation_id": installation_id,
                        }
                    )
                if len(items) < 100:
                    break
                page += 1
        app_repositories.sort(key=lambda item: str(item["full_name"]).casefold())
        return {
            "auth_type": self.auth_type,
            "app_id": self.app_id,
            "count": len(app_repositories),
            "repositories": json_array(
                app_repositories,
                context="GitHub App repositories",
            ),
        }

    def refresh_rate_limits(self, repository: str = "") -> JsonObject:
        token = ""
        auth_mode = "anonymous"
        access_mode = "public_anonymous"
        if self.public_only:
            token = self.token
            auth_mode = "public_reader" if token else "public_anonymous"
            access_mode = "public_authenticated" if token else "public_anonymous"
        elif self.token:
            token = self.token
            auth_mode = "user_token"
            access_mode = "user_token"
        else:
            token = (
                self._installation_token(repository)
                if repository.strip()
                else self._any_installation_token()
            )
            auth_mode = "installation"
            access_mode = "installation"
        _, payload = self._request(
            "GET",
            f"{_GITHUB_API}/rate_limit",
            token=token or None,
            auth_mode=auth_mode,
        )
        return {
            "account_id": self.account_id,
            "auth_type": self.auth_type,
            "access_mode": access_mode,
            "repository": repository.strip(),
            "public_reader_account": self.public_reader_account,
            "provider": json_value(payload, context="GitHub rate limit response"),
            "observed": self.rate_limit_status()["entries"],
        }

    def _repository_metadata(
        self,
        repository: str,
        *,
        refresh: bool = False,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        key = repository.casefold()
        now = time.monotonic()
        if not refresh and self.repository_cache_ttl_seconds > 0:
            with self._cache_lock:
                cached = self._repository_cache.get(key)
                if cached is not None and cached[0] > now:
                    return dict(cached[1])

        _, result = self._repo_request(repository, "GET", f"/repos/{repository}")
        try:
            payload = json_object(result, context="GitHub repository response")
        except ValueError as exc:
            raise GitHubAgentError("unexpected repository response") from exc
        metadata: JsonObject = {
            "repository": json_str(payload.get("full_name"), default=repository),
            "default_branch": json_str(payload.get("default_branch")),
            "private": json_bool(payload.get("private")),
            "archived": json_bool(payload.get("archived")),
            "fork": json_bool(payload.get("fork")),
        }
        if self.repository_cache_ttl_seconds > 0:
            with self._cache_lock:
                self._repository_cache[key] = (
                    time.monotonic() + self.repository_cache_ttl_seconds,
                    dict(metadata),
                )
        return metadata

    def status(self, repository: str) -> JsonObject:
        repository = self._assert_allowed(repository)
        result = self._repository_metadata(repository)
        response: JsonObject = {
            "repository": str(result["repository"]),
            "default_branch": str(result["default_branch"]),
            "private": bool(result["private"]),
            "auth_type": self.auth_type,
            "status": "ok",
        }
        if self.public_only:
            response["auth_type"] = "public"
            response["access_mode"] = "public_authenticated" if self.token else "public_anonymous"
            response["public_reader_account"] = self.public_reader_account
            response["rate_limits"] = self.rate_limit_status()
            return response
        if self.token:
            response["access_mode"] = "user_token"
            response["rate_limits"] = self.rate_limit_status()
            return response
        response["app_id"] = self.app_id
        response["installation_id"] = self._installation_id(repository)
        response["access_mode"] = "installation"
        response["rate_limits"] = self.rate_limit_status()
        return response
