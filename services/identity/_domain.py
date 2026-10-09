"""Identity domain values. No HTTP/ORM dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from common.platform_ids import UserId


class UserRole(StrEnum):
    USER = "user"
    SUPERUSER = "superuser"


class InvitationKind(StrEnum):
    SYSTEM = "system"
    REGISTRATION = "registration"
    PASSWORD_RESET = "password_reset"


@dataclass(frozen=True, slots=True)
class User:
    id: UserId
    username: str
    role: UserRole
    enabled: bool
    credential_version: int


@dataclass(frozen=True, slots=True)
class RegistrationInvitation:
    token_digest: str
    kind: InvitationKind
    issued_at: datetime
    expires_at: datetime | None
    used_at: datetime | None
    revoked_at: datetime | None


def canonical_username(username: str) -> str:
    canonical = username.strip().casefold()
    if not (3 <= len(canonical) <= 128) or not canonical.replace("_", "").isalnum():
        raise ValueError("username must be 3-128 letters, digits or underscores")
    return canonical
