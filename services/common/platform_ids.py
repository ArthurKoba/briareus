"""Opaque identifiers shared as vocabulary, never as a global entity model."""

from typing import NewType
from uuid import UUID

UserId = NewType("UserId", UUID)
TeamId = NewType("TeamId", UUID)
PlatformProjectId = NewType("PlatformProjectId", UUID)
AgentIdentityId = NewType("AgentIdentityId", UUID)
AgentSessionUuid = NewType("AgentSessionUuid", UUID)
