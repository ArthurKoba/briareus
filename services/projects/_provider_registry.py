"""Provider-specific settings validation. Secrets are never provider metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from common.platform_errors import InvalidInput


class ProviderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    base_url: str = ""
    display_name: str = Field(default="", max_length=128)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("display_name must not contain control characters")
        return value

    @field_validator("base_url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        if not value:
            return ""
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or len(value) > 2048
        ):
            raise ValueError("provider endpoint must be a bare HTTPS origin/path")
        host = parsed.hostname.casefold()
        if any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("provider URL contains prohibited characters")
        if "%" in parsed.netloc:
            raise ValueError("encoded host and IPv6 zone identifiers are forbidden")
        try:
            address = ip_address(host)
        except ValueError:
            if (
                "." not in host
                or len(host) > 253
                or host.endswith((".local", ".localhost", ".internal", ".lan", ".home", ".onion"))
            ):
                raise ValueError("provider endpoint requires a public DNS name") from None
            labels = host.split(".")
            if any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", part) or len(part) > 63
                for part in labels
            ):
                raise ValueError("invalid provider DNS hostname") from None
            if not labels[-1].isalpha() or len(labels[-1]) < 2:
                raise ValueError("provider hostname needs a public DNS suffix") from None
        else:
            if not address.is_global:
                raise ValueError("provider endpoint IP is not globally routable")
        try:
            port = parsed.port
        except ValueError:
            raise ValueError("invalid provider endpoint port") from None
        if port is not None and port not in {443, 8443}:
            raise ValueError("provider endpoint port is not allowed")
        return value.rstrip("/")


class GitHubOptions(ProviderOptions):
    installation_id: int | None = Field(default=None, gt=0)
    organization: str = Field(default="", max_length=128)

    @field_validator("organization")
    @classmethod
    def validate_org(cls, value: str) -> str:
        if value and not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", value):
            raise ValueError("organization must be a GitHub organization slug")
        return value


class GitLabOptions(ProviderOptions):
    namespace: str = Field(default="", max_length=128)

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, value: str) -> str:
        if value and not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", value):
            raise ValueError("namespace must contain only GitLab namespace segments")
        return value


class InfrastructureOptions(ProviderOptions):
    tenant: str = Field(default="", max_length=128)

    @field_validator("tenant")
    @classmethod
    def validate_tenant(cls, value: str) -> str:
        if value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
            raise ValueError("tenant must be a platform identifier")
        return value


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    provider: str
    auth_types: frozenset[str]
    schema: type[ProviderOptions]


_REGISTRY = {
    "github": ProviderDefinition(
        "github", frozenset({"personal_token", "github_app"}), GitHubOptions
    ),
    "gitlab": ProviderDefinition("gitlab", frozenset({"personal_token", "oauth"}), GitLabOptions),
    "coolify": ProviderDefinition("coolify", frozenset({"api_token"}), InfrastructureOptions),
    "signoz": ProviderDefinition("signoz", frozenset({"api_token"}), InfrastructureOptions),
    "grafana": ProviderDefinition("grafana", frozenset({"api_token"}), InfrastructureOptions),
    "zoomies": ProviderDefinition("zoomies", frozenset({"api_token"}), InfrastructureOptions),
}


def provider_names() -> tuple[str, ...]:
    return tuple(_REGISTRY)


def provider_auth_types(provider: str) -> tuple[str, ...]:
    definition = _REGISTRY.get(provider.strip().casefold())
    if definition is None:
        raise InvalidInput("unsupported provider")
    return tuple(sorted(definition.auth_types))


def validate_provider(
    provider: str,
    auth_type: str,
    options: dict[str, Any],
) -> dict[str, object]:
    name = provider.strip().casefold()
    definition = _REGISTRY.get(name)
    if definition is None or auth_type not in definition.auth_types:
        raise InvalidInput("unsupported provider authentication configuration")
    try:
        validated = definition.schema.model_validate(options)
    except (ValidationError, ValueError):
        # Do not copy raw input/ValidationError (which may embed secrets).
        raise InvalidInput("invalid provider-specific configuration") from None
    if name == "github" and auth_type == "github_app":
        assert isinstance(validated, GitHubOptions)
        if validated.installation_id is None:
            raise InvalidInput("GitHub App configuration requires installation_id")
    return validated.model_dump(mode="json")
