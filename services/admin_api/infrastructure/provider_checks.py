from __future__ import annotations

import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import jwt

from admin_api.domain.accounts import Account, AuthType, Provider
from common.models import json_loads, json_object


class ProviderConnectionVerifier:
    def verify(self, account: Account, credential: str) -> dict[str, object]:
        if account.provider is Provider.GITHUB:
            return self._verify_github(account, credential)
        if account.provider is Provider.GITLAB:
            return self._verify_gitlab(account, credential)
        if account.provider is Provider.SIGNOZ:
            return self._verify_signoz(account, credential)
        return self._verify_coolify(account, credential)

    @staticmethod
    def _verify_github(account: Account, credential: str) -> dict[str, object]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "mcp-bridge-admin-api",
            "X-GitHub-Api-Version": "2026-03-10",
        }
        endpoint = "/user"
        if account.auth_type is AuthType.GITHUB_APP:
            if not account.external_id.isdigit():
                raise ValueError("GitHub App external_id must be numeric APP_ID")
            now = int(time.time())
            token = jwt.encode(
                {"iat": now - 60, "exp": now + 9 * 60, "iss": account.external_id},
                credential.replace("\\n", "\n"),
                algorithm="RS256",
            )
            headers["Authorization"] = f"Bearer {token}"
            endpoint = "/app"
        elif account.auth_type is AuthType.GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {credential.strip()}"
        else:
            raise ValueError("unsupported GitHub auth type")
        request = urllib.request.Request(
            account.base_url.rstrip("/") + endpoint,
            method="GET",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:2048].decode("utf-8", "replace")
            raise ValueError(f"GitHub verification failed HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"GitHub verification transport error: {exc.reason}") from exc
        data = json_object(json_loads(raw, context="GitHub app verification"))
        return {
            "ok": True,
            "provider": "github",
            "account": account.alias,
            "auth_type": account.auth_type.value,
            "app_id": account.external_id or None,
            "login": data.get("login"),
            "slug": data.get("slug"),
            "name": data.get("name"),
        }

    @staticmethod
    def _context(account: Account) -> ssl.SSLContext | None:
        parsed = urllib.parse.urlsplit(account.base_url)
        if parsed.scheme != "https":
            return None
        if not account.verify_tls:
            return ssl._create_unverified_context()
        if account.ca_cert_pem:
            return ssl.create_default_context(cadata=account.ca_cert_pem.replace("\\n", "\n"))
        return ssl.create_default_context()

    @classmethod
    def _verify_signoz(cls, account: Account, token: str) -> dict[str, object]:
        request = urllib.request.Request(
            account.base_url.rstrip("/") + "/api/v1/service_accounts/me",
            method="GET",
            headers={
                "Accept": "application/json",
                "SIGNOZ-API-KEY": token.strip(),
                "User-Agent": "mcp-bridge-admin-api",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=15,
                context=cls._context(account),
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:2048].decode("utf-8", "replace")
            raise ValueError(f"SigNoz verification failed HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"SigNoz verification transport error: {exc.reason}") from exc
        data = json_object(json_loads(raw, context="SigNoz service account verification"))
        return {
            "ok": True,
            "provider": "signoz",
            "account": account.alias,
            "base_url": account.base_url,
            "service_account": data,
        }

    @classmethod
    def _verify_coolify(cls, account: Account, token: str) -> dict[str, object]:
        request = urllib.request.Request(
            account.base_url.rstrip("/") + "/api/v1/teams/current",
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token.strip()}",
                "User-Agent": "mcp-bridge-admin-api",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=15,
                context=cls._context(account),
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:2048].decode("utf-8", "replace")
            raise ValueError(f"Coolify verification failed HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"Coolify verification transport error: {exc.reason}") from exc
        data = json_object(json_loads(raw, context="Coolify team verification"))
        return {
            "ok": True,
            "provider": "coolify",
            "account": account.alias,
            "base_url": account.base_url,
            "team": data,
        }

    @staticmethod
    def _verify_gitlab(account: Account, token: str) -> dict[str, object]:
        parsed = urllib.parse.urlsplit(account.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("GitLab base_url must be an http(s) origin")
        headers = {"Accept": "application/json", "User-Agent": "mcp-bridge-admin-api"}
        if account.auth_type is AuthType.PRIVATE_TOKEN:
            headers["PRIVATE-TOKEN"] = token
        elif account.auth_type is AuthType.BEARER:
            headers["Authorization"] = f"Bearer {token}"
        elif account.auth_type is AuthType.JOB_TOKEN:
            headers["JOB-TOKEN"] = token
        else:
            raise ValueError("unsupported GitLab auth type")

        context: ssl.SSLContext | None = None
        if parsed.scheme == "https":
            if not account.verify_tls:
                context = ssl._create_unverified_context()
            elif account.ca_cert_pem:
                context = ssl.create_default_context(
                    cadata=account.ca_cert_pem.replace("\\n", "\n")
                )
            else:
                context = ssl.create_default_context()
        request = urllib.request.Request(
            account.base_url.rstrip("/") + "/api/v4/user",
            method="GET",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=15, context=context) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:2048].decode("utf-8", "replace")
            raise ValueError(f"GitLab verification failed HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"GitLab verification transport error: {exc.reason}") from exc
        data = json_object(json_loads(raw, context="GitLab user verification"))
        return {
            "ok": True,
            "provider": "gitlab",
            "account": account.alias,
            "user_id": data.get("id"),
            "username": data.get("username"),
            "name": data.get("name"),
            "base_url": account.base_url,
        }
