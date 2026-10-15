"""Minimal current Platform membership proof consumed by Authorization.

A verified Rauthy subject and current Project membership MUST originate from
a separate authenticated owner request, never an incoming MCP header.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class VerifiedProjectMembership:
    rauthy_issuer: str
    rauthy_subject: str
    actor_uuid: UUID
    project_uuid: UUID
    expires_at: datetime
