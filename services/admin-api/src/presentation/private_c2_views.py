"""Trusted private owner projection API: UI display is never authority.

Project/Team views are independently scoped current owner source results,
and AgentSession pages MUST have current pinned Access JWS/source revision.
No source row or WebSocket projection gives access to an effect by itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from common.owner_bff_models import (
    OwnerPage,
    OwnerProjectView,
    OwnerTeamView,
    VerifiedAdminCaller,
)


class TrustedCurrentOwnerPagesPort(Protocol):
    async def visible_projects(
        self, caller: VerifiedAdminCaller, *, after_id: UUID | None, limit: int
    ) -> OwnerPage[OwnerProjectView]:
        """Independently scoped, live Control/Identity display source."""
        ...

    async def visible_teams(
        self, caller: VerifiedAdminCaller, *, after_id: UUID | None, limit: int
    ) -> OwnerPage[OwnerTeamView]:
        """Independently scoped, live Control/Identity display source."""
        ...


class PrivateAgentSessionView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sessionUuid: UUID
    projectId: UUID
    actorUserId: UUID
    grants: tuple[str, ...]
    status: str = Field(pattern=r"^(active|expired|revoked|closed)$")
    accessRevision: int = Field(ge=1)
    hardExpiresAtUtc: datetime

    @model_validator(mode="after")
    def scope_fence(self) -> PrivateAgentSessionView:
        if (
            any(
                value.version != 4 for value in (self.sessionUuid, self.projectId, self.actorUserId)
            )
            or self.hardExpiresAtUtc.tzinfo is None
            or any(not 1 <= len(x) <= 128 or not x.isascii() for x in self.grants)
        ):
            raise ValueError("private Access session display not source scoped")
        return self


class PrivateAgentSessionPage(BaseModel):
    """Already signed/pinned and freshly verified by private Access source port."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    actorUserId: UUID
    projectId: UUID
    sessions: tuple[PrivateAgentSessionView, ...] = Field(max_length=100)
    observedAtUtc: datetime
    expiresAtUtc: datetime
    sourceJwsSha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def current_source(self) -> PrivateAgentSessionPage:
        now = datetime.now(UTC)
        if (
            self.actorUserId.version != 4
            or self.projectId.version != 4
            or self.observedAtUtc.tzinfo is None
            or self.expiresAtUtc.tzinfo is None
            or not self.observedAtUtc <= now < self.expiresAtUtc
            or self.expiresAtUtc > self.observedAtUtc + timedelta(seconds=5)
            or any(
                item.projectId != self.projectId
                or item.actorUserId != self.actorUserId
                or (item.status == "active" and item.hardExpiresAtUtc <= now)
                for item in self.sessions
            )
        ):
            raise ValueError("Access session display must have pinned current origin")
        return self


class TrustedCurrentAccessSessionsPort(Protocol):
    async def visible_sessions(
        self,
        *,
        caller: VerifiedAdminCaller,
        project_id: UUID,
    ) -> PrivateAgentSessionPage:
        """Verify Access source JWS, current User+Project grant and hard TTL.

        Return only a short-lived scoped, release-pinned display; do NOT return
        refresh/service JWTs, session secrets, raw SQL or outbox.
        """
        ...
