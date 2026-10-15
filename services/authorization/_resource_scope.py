"""Canonical per-Hand effect selectors and exact durable scoped grant matching.

A request selector is NOT proof of a protected resource. The authenticated
Hand peer must attest the same canonical selector independently from the
actual tool and its resolved owner resource before Cedar can evaluate.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from authorization._action_audiences import HAND_EFFECT_ACTIONS
from common.platform_ids import PlatformProjectId

HandName = Literal["files", "terminal", "web", "svc", "reverse", "infrastructure"]

_KINDS: dict[str, frozenset[str]] = {
    "files": frozenset({"workspace_path"}),
    "terminal": frozenset({"workspace", "job"}),
    "web": frozenset({"browser_session", "origin"}),
    "svc": frozenset({"repository"}),
    "reverse": frozenset({"analysis_project", "artifact"}),
    "infrastructure": frozenset({"application"}),
}
_TOOL_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}")
_FILES_PROJECT_SELECTOR = re.compile(
    r"project-path-v1:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([0-9a-f]{64})",
    re.ASCII,
)


class EffectResource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(min_length=1, max_length=64)
    id: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def canonical(self) -> EffectResource:
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.kind)
            or not unicodedata.is_normalized("NFC", self.id)
            or self.id.strip() != self.id
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in self.id)
        ):
            raise ValueError("resource selector must be canonical")
        return self


def _files_selector_project(hand: str, resource: EffectResource) -> UUID | None:
    # Runtime owns canonical path resolution and A6 hashing. Authorization
    # validates only the reserved wire namespace; a matching selector is
    # never a replacement for independently signed Files-owner evidence.
    if not resource.id.startswith("project-path-"):
        return None
    match = _FILES_PROJECT_SELECTOR.fullmatch(resource.id)
    if hand != "files" or resource.kind != "workspace_path" or match is None:
        raise ValueError("invalid versioned Files Project selector")
    project = UUID(match.group(1))
    if project.version != 4 or str(project) != match.group(1):
        raise ValueError("Files selector Project must be canonical UUIDv4")
    return project


def validate_resource_scope(hand: str, tool: str, resource: EffectResource) -> None:
    if (
        hand not in _KINDS
        or resource.kind not in _KINDS[hand]
        or _TOOL_PATTERN.fullmatch(tool) is None
    ):
        raise ValueError("unsupported Hand/tool/resource selector")
    _files_selector_project(hand, resource)


def validate_project_resource_scope(
    *, project_uuid: UUID, hand: str, tool: str, resource: EffectResource
) -> None:
    validate_resource_scope(hand, tool, resource)
    selected_project = _files_selector_project(hand, resource)
    if selected_project is not None and selected_project != project_uuid:
        raise ValueError("Files selector belongs to another Project")


def validate_effect_scope(hand: str, tool: str, action: str, resource: EffectResource) -> None:
    validate_resource_scope(hand, tool, resource)
    if action not in HAND_EFFECT_ACTIONS.get(hand, frozenset()):
        raise ValueError("action cannot be executed by this Hand")


def resource_key(hand: str, tool: str, resource: EffectResource) -> str:
    validate_resource_scope(hand, tool, resource)
    # JSON array prevents ':' or '/' collisions in workspace paths/URLs.
    return json.dumps(
        [hand, tool, resource.kind, resource.id],
        ensure_ascii=True,
        separators=(",", ":"),
    )


def stored_grant_matches(
    *,
    stored: object,
    hand: str,
    tool: str,
    action: str,
    resource: EffectResource,
    project_uuid: UUID | None = None,
) -> bool:
    if not isinstance(stored, list) or not 1 <= len(stored) <= 32:
        return False
    try:
        validate_effect_scope(hand, tool, action, resource)
        if project_uuid is not None:
            validate_project_resource_scope(
                project_uuid=project_uuid, hand=hand, tool=tool, resource=resource
            )
        expected = resource_key(hand, tool, resource)
    except ValueError:
        return False
    matched = False
    for item in stored:
        if not isinstance(item, dict) or set(item) != {"hand", "tool", "action", "resource"}:
            return False
        scope = item["resource"]
        if not isinstance(scope, dict) or set(scope) != {"kind", "id"}:
            return False
        try:
            parsed = EffectResource.model_validate(scope)
            validate_effect_scope(item["hand"], item["tool"], item["action"], parsed)
            if project_uuid is not None:
                validate_project_resource_scope(
                    project_uuid=project_uuid, hand=item["hand"], tool=item["tool"], resource=parsed
                )
            actual = resource_key(item["hand"], item["tool"], parsed)
        except (ValueError, TypeError):
            return False
        if item["action"] == action and actual == expected:
            matched = True
    return matched


@dataclass(frozen=True, slots=True)
class VerifiedResourceOwnerProof:
    """Actual owner-attested scope; not a JSON request or implicit Project grant."""

    project_uuid: UUID
    hand: HandName
    tool: str
    action: str
    resource: EffectResource
    revision: int
    expires_at: datetime


class TrustedResourceOwnerPort(Protocol):
    def verify_current_scope(
        self, *, project_uuid: PlatformProjectId, scope: dict[str, object]
    ) -> VerifiedResourceOwnerProof | None:
        """Verify preobtained signed owner proof locally, without DB/network I/O."""
        ...


def matches_current_owner(
    proof: object, *, project_uuid: PlatformProjectId, scope: dict[str, object]
) -> bool:
    if not isinstance(proof, VerifiedResourceOwnerProof):
        return False
    try:
        requested = EffectResource.model_validate(scope["resource"])
        validate_effect_scope(scope["hand"], scope["tool"], scope["action"], requested)
        validate_project_resource_scope(
            project_uuid=project_uuid, hand=scope["hand"], tool=scope["tool"], resource=requested
        )
        request_key = resource_key(scope["hand"], scope["tool"], requested)
        validate_effect_scope(proof.hand, proof.tool, proof.action, proof.resource)
        validate_project_resource_scope(
            project_uuid=project_uuid, hand=proof.hand, tool=proof.tool, resource=proof.resource
        )
        proof_key = resource_key(proof.hand, proof.tool, proof.resource)
    except (KeyError, ValueError, TypeError):
        return False
    now = datetime.now(UTC)
    return (
        isinstance(proof.project_uuid, UUID)
        and proof.project_uuid == project_uuid
        and proof.action == scope.get("action")
        and request_key == proof_key
        and type(proof.revision) is int
        and proof.revision >= 1
        and isinstance(proof.expires_at, datetime)
        and proof.expires_at.tzinfo is not None
        and now < proof.expires_at <= now + timedelta(seconds=30)
    )


def normalized_resource_grants(
    requested: object, *, allowed_actions: set[str], project_uuid: UUID | None = None
) -> list[dict[str, object]]:
    """Normalize exact owner-approved effect scopes for durable SQL JSONB."""
    if not isinstance(requested, list) or len(requested) > 32:
        raise ValueError("resource grants must be a bounded list")
    normalized: list[tuple[str, str, str, str, str]] = []
    for item in requested:
        if not isinstance(item, dict) or set(item) != {"hand", "tool", "action", "resource"}:
            raise ValueError("resource grant shape invalid")
        try:
            action = item["action"]
            if not isinstance(action, str) or action not in allowed_actions:
                raise ValueError("resource scope exceeds approved action")
            raw = EffectResource.model_validate(item["resource"])
            hand = item["hand"]
            tool = item["tool"]
            validate_effect_scope(hand, tool, action, raw)
            if project_uuid is not None:
                validate_project_resource_scope(
                    project_uuid=project_uuid, hand=hand, tool=tool, resource=raw
                )
        except (ValueError, TypeError) as exc:
            raise ValueError("resource grant selector invalid") from exc
        normalized.append((hand, tool, action, raw.kind, raw.id))
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate resource grant selector")
    return [
        {
            "hand": hand,
            "tool": tool,
            "action": action,
            "resource": {"kind": kind, "id": resource_id},
        }
        for hand, tool, action, kind, resource_id in sorted(normalized)
    ]
