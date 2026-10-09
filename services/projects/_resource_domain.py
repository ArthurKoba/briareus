"""Reusable Team/Project resource vocabulary; not Project or Team aggregates.

A resource has exactly one owner. A Project receives Team-owned resources only
by current Team ownership and current authorization; no copies or overrides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from common.platform_errors import InvalidInput
from common.platform_ids import PlatformProjectId, TeamId


class ResourceScope(StrEnum):
    ALL = "all"
    TEAM = "team"
    PROJECT = "project"


class OwnerScope(StrEnum):
    TEAM = "team"
    PROJECT = "project"


class ResourceKind(StrEnum):
    INTEGRATION = "integration"
    VARIABLE = "variable"


@dataclass(frozen=True, slots=True)
class ResourceOwner:
    scope: OwnerScope
    owner_id: UUID

    @property
    def team_id(self) -> TeamId | None:
        return TeamId(self.owner_id) if self.scope is OwnerScope.TEAM else None

    @property
    def project_id(self) -> PlatformProjectId | None:
        return PlatformProjectId(self.owner_id) if self.scope is OwnerScope.PROJECT else None


@dataclass(frozen=True, slots=True)
class EffectiveResource:
    resource_id: UUID
    kind: ResourceKind
    owner: ResourceOwner
    name: str
    key: str
    version: int
    inherited: bool
    is_secret: bool
    provider: str | None = None
    auth_type: str | None = None
    value: str | None = None
    display_name: str = ""
    provider_settings: dict[str, object] | None = None
    credential_configured: bool = False
    connection_status: str | None = None
    updated_at: datetime | None = None

    @property
    def origin(self) -> OwnerScope:
        return self.owner.scope


class AmbiguousResource(InvalidInput):
    code = "resource_ambiguous"
    status_code = 409


def canonical_alias(value: str) -> tuple[str, str]:
    alias = value.strip()
    if not 1 <= len(alias) <= 128:
        raise InvalidInput("alias must contain 1-128 characters")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", alias, flags=re.ASCII):
        raise InvalidInput("alias must start with a letter and use letters/digits/_.-")
    return alias, alias.casefold()


def canonical_variable_name(value: str) -> str:
    key = value.strip().upper()
    if len(key) > 128 or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key, flags=re.ASCII):
        raise InvalidInput("variable name must be an identifier up to 128 characters")
    return key
