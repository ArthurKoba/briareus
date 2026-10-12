from __future__ import annotations

import threading

from common.admin_api_client import AdminApiClient
from common.models import JsonObject, json_array
from common.settings import GitHubPolicySettings

from .github_agent import GitHubAgentError
from .github_identity import GitHubPrettyIdentityClient


class GitHubRuntimeContext:
    def __init__(
        self,
        admin_api: AdminApiClient,
        policy: GitHubPolicySettings,
    ) -> None:
        self.admin_api = admin_api
        self.policy = policy
        self._lock = threading.Lock()
        self._clients: dict[
            tuple[str, str],
            tuple[str, GitHubPrettyIdentityClient],
        ] = {}

    def list_accounts(self) -> JsonObject:
        result = self.admin_api.list_accounts(provider="github").to_json()
        accounts = result.get("accounts")
        if isinstance(accounts, list):
            for account in accounts:
                if not isinstance(account, dict):
                    continue
                auth_type = str(account.get("auth_type", ""))
                account["potential_capabilities"] = json_array(
                    self._potential_capabilities(auth_type),
                    context="GitHub potential capabilities",
                )
                account["permission_scope"] = "repository-dependent"
                account["preferred_selector"] = str(account.get("alias", ""))
                account["selector_stability"] = "stable_alias"
            accounts.append(
                {
                    "id": "public",
                    "alias": "public",
                    "provider": "github",
                    "auth_type": "public",
                    "base_url": "https://api.github.com",
                    "external_id": None,
                    "verify_tls": True,
                    "ca_cert_pem": None,
                    "enabled": True,
                    "created_at": "",
                    "updated_at": "",
                    "potential_capabilities": ["repository_read", "git_history"],
                    "permission_scope": "public-repositories-only",
                    "preferred_selector": "public",
                    "selector_stability": "stable_alias",
                    "transport_auth": "authenticated_reader",
                    "reader_selector": self.policy.public_reader_account or "auto",
                    "anonymous_fallback": self.policy.public_allow_anonymous_fallback,
                }
            )
            result["count"] = len(accounts)
        return result

    @staticmethod
    def _potential_capabilities(auth_type: str) -> list[str]:
        if auth_type == "public":
            return [
                "repository_read",
                "issues",
                "pull_requests",
                "actions",
                "checks",
                "git_history",
            ]
        capabilities = [
            "repository_read",
            "repository_write",
            "issues",
            "pull_requests",
            "reviews",
            "actions",
            "checks",
            "git_history",
        ]
        if auth_type == "github_app":
            capabilities.append("installation_scoped_access")
        else:
            capabilities.append("user_token_scoped_access")
        return capabilities

    def account_capabilities(
        self,
        account_id: str,
        repository: str = "",
    ) -> JsonObject:
        client = self._client(account_id)
        result = client.account_capabilities()
        result["potential_capabilities"] = json_array(
            self._potential_capabilities(client.auth_type),
            context="GitHub potential capabilities",
        )
        result["permission_scope"] = (
            "public-repositories-only"
            if client.public_only
            else "repository-dependent"
        )
        if repository.strip():
            result["repository"] = client.capabilities(repository.strip())
        return result

    def _public_reader_selector(self) -> str:
        configured = self.policy.public_reader_account.strip()
        if configured:
            return configured
        accounts = self.admin_api.list_accounts(provider="github").accounts
        candidates = [
            account.alias
            for account in accounts
            if account.enabled and account.auth_type == "github_token" and account.alias
        ]
        preferred = [item for item in candidates if item.casefold() == "authenticated"]
        if len(preferred) == 1:
            return preferred[0]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            if self.policy.public_allow_anonymous_fallback:
                return ""
            raise GitHubAgentError(
                "GitHub public read-only access requires an authenticated reader; "
                "configure GITHUB_PUBLIC_READER_ACCOUNT to a github_token account"
            )
        raise GitHubAgentError(
            "multiple github_token accounts can act as the public reader; "
            "set GITHUB_PUBLIC_READER_ACCOUNT explicitly"
        )

    def _public_client(self) -> GitHubPrettyIdentityClient:
        selector = self._public_reader_selector()
        if not selector:
            return GitHubPrettyIdentityClient(
                account_id="public",
                auth_type="public",
                public_only=True,
                public_reader_account="",
                protected_branches=self.policy.protected_branches,
                required_checks=self.policy.required_checks,
                required_reviewers=self.policy.required_reviewers,
            )
        account = self.admin_api.resolve_account(selector, provider="github")
        if not account.enabled:
            raise GitHubAgentError(f"GitHub public reader account is disabled: {selector}")
        if account.auth_type != "github_token":
            raise GitHubAgentError(
                "GITHUB_PUBLIC_READER_ACCOUNT must reference a github_token account; "
                "GitHub App installation tokens cannot read arbitrary repositories outside "
                "their installation scope"
            )
        key = ("public", account.id)
        with self._lock:
            cached = self._clients.get(key)
            if cached is not None and cached[0] == account.updated_at:
                return cached[1]
            credential = account.credential.replace("\\n", "\n").strip()
            if not credential:
                raise GitHubAgentError("GitHub public reader account has no credential")
            client = GitHubPrettyIdentityClient(
                account_id="public",
                token=credential,
                auth_type="public",
                public_only=True,
                public_reader_account=account.alias or account.id,
                protected_branches=self.policy.protected_branches,
                required_checks=self.policy.required_checks,
                required_reviewers=self.policy.required_reviewers,
            )
            self._clients[key] = (account.updated_at, client)
            return client

    def _client(self, account_id: str) -> GitHubPrettyIdentityClient:
        selector = account_id.strip().casefold()
        if selector in {"public", "anonymous"}:
            return self._public_client()
        account = self.admin_api.resolve_account(account_id, provider="github")
        key = ("github", account.id)
        with self._lock:
            cached = self._clients.get(key)
            if cached is not None and cached[0] == account.updated_at:
                return cached[1]
            client = GitHubPrettyIdentityClient.from_account(account, self.policy)
            self._clients[key] = (account.updated_at, client)
            return client

    def client(self, account_id: str) -> GitHubPrettyIdentityClient:
        return self._client(account_id)

    def clear(self) -> None:
        with self._lock:
            self._clients.clear()
