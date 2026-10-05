from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

AccessLevel = Literal["read_only", "full_access"]
AccountScope = Literal["none", "all", "selected"]
SessionStatus = Literal["active", "revoked", "expired"]
EnforcementMode = Literal["unrestricted", "session_enforced"]
RequestKind = Literal["full_access", "extension"]


class OAuthContext(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=512)
    oauth_session_id: str = Field(min_length=1, max_length=128)


class SessionOpenRequest(OAuthContext):
    surface_id: int
    label: str = Field("", max_length=256)


class SessionValidateRequest(OAuthContext):
    surface_id: int
    session_uid: str = Field("", max_length=256)
    tool_name: str = Field("", max_length=256)
    requires_full_access: bool = False
    account_id: str = Field("", max_length=256)


class SessionUpdateRequest(OAuthContext):
    surface_id: int
    session_uid: str = Field(min_length=16, max_length=256)
    label: str = Field("", max_length=256)


class FullAccessRequest(OAuthContext):
    surface_id: int
    session_uid: str = Field(min_length=16, max_length=256)
    account_scope: AccountScope = "none"
    account_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("account_ids")
    @classmethod
    def _normalize_account_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class ExtensionRequest(OAuthContext):
    surface_id: int
    session_uid: str = Field(min_length=16, max_length=256)
    requested_expires_at: int = Field(ge=0)


class AdminResolveRequest(BaseModel):
    admin_user_id: str = Field(min_length=1, max_length=128)
    approve: bool
    account_scope: AccountScope | None = None
    account_ids: list[str] | None = Field(default=None, max_length=100)
    expires_at: int | None = Field(default=None, ge=0)


class SurfaceControlUpdate(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    surface_id: int
    mode: EnforcementMode


class SessionSnapshot(BaseModel):
    id: str
    uid: str
    user_id: str
    oauth_client_id: str
    oauth_session_id: str
    surface_id: int
    access_level: AccessLevel
    account_scope: AccountScope
    account_ids: list[str]
    status: SessionStatus
    label: str
    expires_at: int


class ValidationResult(BaseModel):
    allowed: bool
    code: str
    session: SessionSnapshot | None = None
    retry_after_seconds: int = 0


class AccessRequestView(BaseModel):
    id: str
    session_id: str
    kind: RequestKind
    status: str
    requested_access_level: str
    requested_account_scope: AccountScope
    requested_account_ids: list[str]
    requested_expires_at: int
