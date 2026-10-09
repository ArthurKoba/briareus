"""Projects owns the exclusive User/Team owner reference."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from common.platform_db import PlatformBase


class ProjectRow(PlatformBase):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "(owner_user_id IS NOT NULL) <> (owner_team_id IS NOT NULL)",
            name="ck_project_exclusive_owner",
        ),
        Index("ix_project_owner_user", "owner_user_id"),
        Index("ix_project_owner_team", "owner_team_id"),
        {"schema": "projects"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255))
    owner_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("identity.users.id", ondelete="RESTRICT")
    )
    owner_team_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("teams.teams.id", ondelete="RESTRICT")
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    resource_revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
