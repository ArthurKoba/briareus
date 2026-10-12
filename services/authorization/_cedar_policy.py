"""Cedar decision adapter over facts already verified by the Authorization owner.

This module does NOT authenticate OAuth tokens or load grants from clients.
The caller must obtain grant/version/session facts from trusted owner storage.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from cedarpy import PolicySet, is_authorized


class CedarPolicyError(Exception):
    """The Authorization owner cannot initialize its trusted policy set."""


@dataclass(frozen=True, slots=True)
class CedarOperation:
    actor_uuid: UUID
    agent_session_uuid: UUID
    project_uuid: UUID
    action: str
    resource_type: str
    resource_uuid: UUID


@dataclass(frozen=True, slots=True)
class CurrentGrant:
    """Trusted snapshot from the Authorization database, NEVER HTTP input."""

    actor_uuid: UUID
    agent_session_uuid: UUID
    project_uuid: UUID
    action: str
    resource_uuid: UUID | None
    active: bool
    expires_at: datetime
    version: int
    minimum_current_version: int
    is_elevated: bool = False


class CedarPolicyEvaluator:
    """Keep a compiled Cedar policy and fail closed on stale grants/errors."""

    def __init__(self, policy_text: str) -> None:
        if not policy_text.strip():
            raise CedarPolicyError("Authorization Cedar policy is empty")
        try:
            self._policy_set = PolicySet.from_str(policy_text)
        except (TypeError, ValueError) as exc:
            raise CedarPolicyError("Authorization Cedar policy cannot be parsed") from exc

    def permits(
        self,
        operation: CedarOperation,
        grant: CurrentGrant,
        *,
        trusted_entities: Sequence[Mapping[str, object]] = (),
        now: datetime | None = None,
    ) -> bool:
        instant = datetime.now(UTC) if now is None else now
        if (
            instant.tzinfo is None
            or grant.expires_at.tzinfo is None
            or not grant.active
            or grant.expires_at <= instant
            or grant.version < 1
            or grant.minimum_current_version < 1
            or grant.version < grant.minimum_current_version
            or grant.actor_uuid != operation.actor_uuid
            or grant.agent_session_uuid != operation.agent_session_uuid
            or grant.project_uuid != operation.project_uuid
            or grant.action != operation.action
            or (grant.resource_uuid is not None and grant.resource_uuid != operation.resource_uuid)
            or not operation.action
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", operation.resource_type) is None
        ):
            return False

        # JSON quoting prevents identifiers or tool names from being injected
        # into the Cedar entity syntax. Owner APIs must verify principal,
        # audience, active session, current grant version and entity graph.
        request = {
            "principal": f"User::{json.dumps(str(operation.actor_uuid))}",
            "action": f"Action::{json.dumps(operation.action)}",
            "resource": (f"{operation.resource_type}::{json.dumps(str(operation.resource_uuid))}"),
            "context": {
                "project": str(operation.project_uuid),
                "agentSession": str(operation.agent_session_uuid),
                "grantVersion": grant.version,
                "isElevated": grant.is_elevated,
            },
        }
        # This is a policy layer, not a grant source. Invalid policy, missing
        # entities, or library errors can never turn a denial into an Allow.
        try:
            return is_authorized(request, self._policy_set, list(trusted_entities)).allowed is True
        except Exception:  # Any engine/entity failure is an authorization denial.
            return False
