"""Minimal typed REST DTOs crossing only the first-user Admin/Identity boundary."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FirstUserRegistrationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    user_id: UUID
    role: str = Field(pattern=r"^(user|superuser)$")


class FirstUserLoginReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    access_token: str = Field(min_length=40, max_length=8192)
    token_type: str = Field(pattern="^Bearer$")
    expires_at: datetime


class AuthenticatedFirstUser(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    user_id: UUID
    credential_version: int = Field(ge=1)
    source: str = Field(pattern="^verified-admin-bearer$")
