"""Owner-authenticated Platform Project lookup for signed Rauthy MCP decisions.

Authorization must NOT read the Platform database or infer actor UUID from
a signed IdP subject. A peer-isolated transport to the Platform owner must
bind issuer+subject+Project to an independently signed private delegation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from authorization._decision_api import DecisionAuthorityUnavailable, DecisionScopeDenied
from authorization._rauthy_jwks import load_authority_json
from authorization._rauthy_membership_contract import VerifiedProjectMembership

_MAX_BODY = 4096


@dataclass(frozen=True, slots=True)
class VerifiedPlatformMembershipDelegation:
    bearer: SecretStr
    issuer: str
    subject: str
    project_uuid: UUID
    audience: Literal["briareus:platform"]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerifiedPlatformMembershipResponse:
    status_code: int
    content_type: str
    body: bytes


class TrustedPlatformDecisionPeer(Protocol):
    async def signed_member_delegation(
        self, *, issuer: str, subject: str, project_uuid: UUID
    ) -> VerifiedPlatformMembershipDelegation:
        """Issue a short-lived Project-bound proof from authenticated Rauthy identity."""
        ...

    async def query_project_member(
        self, *, bearer: SecretStr, body: bytes
    ) -> VerifiedPlatformMembershipResponse:
        """Execute fixed private Platform HTTP route via trusted mTLS/Unix peer.

        The transport must enforce exact destination, no redirect, fixed
        method/content type and independently authenticated platform peer.
        """
        ...


class _CurrentMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str
    subject: str
    actor_uuid: UUID
    project_uuid: UUID
    expires_at: datetime


class PlatformCurrentProjectResolver:
    def __init__(self, *, trusted_peer: TrustedPlatformDecisionPeer) -> None:
        if trusted_peer is None:
            raise ValueError("trusted Platform decision peer is required")
        self._peer = trusted_peer

    async def current_member(
        self, *, rauthy_issuer: str, rauthy_subject: str, project_uuid: UUID
    ) -> VerifiedProjectMembership:
        if (
            not isinstance(rauthy_issuer, str)
            or not rauthy_issuer.startswith("https://")
            or not isinstance(rauthy_subject, str)
            or not 1 <= len(rauthy_subject) <= 256
            or not isinstance(project_uuid, UUID)
            or project_uuid.version != 4
        ):
            raise DecisionScopeDenied("invalid Platform membership selector")
        try:
            delegation = await self._peer.signed_member_delegation(
                issuer=rauthy_issuer,
                subject=rauthy_subject,
                project_uuid=project_uuid,
            )
        except Exception:
            raise DecisionAuthorityUnavailable("Platform service delegation unavailable") from None
        now = datetime.now(UTC)
        if (
            not isinstance(delegation, VerifiedPlatformMembershipDelegation)
            or delegation.issuer != rauthy_issuer
            or delegation.subject != rauthy_subject
            or delegation.project_uuid != project_uuid
            or delegation.audience != "briareus:platform"
            or not isinstance(delegation.expires_at, datetime)
            or delegation.expires_at.tzinfo is None
            or not now < delegation.expires_at <= now + timedelta(seconds=30)
        ):
            raise DecisionScopeDenied("Platform delegated subject/project proof invalid")
        credential = delegation.bearer.get_secret_value()
        if (
            not 40 <= len(credential) <= 8192
            or not credential.isascii()
            or any(ch.isspace() for ch in credential)
        ):
            raise DecisionAuthorityUnavailable("signed Platform service bearer invalid")
        body = json.dumps(
            {
                "issuer": rauthy_issuer,
                "subject": rauthy_subject,
                "project_uuid": str(project_uuid),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        if len(body) > _MAX_BODY:
            raise DecisionScopeDenied("Platform selector exceeds maximum")
        try:
            response = await self._peer.query_project_member(bearer=delegation.bearer, body=body)
        except Exception:
            raise DecisionAuthorityUnavailable(
                "private Platform owner request unavailable"
            ) from None
        if not isinstance(response, VerifiedPlatformMembershipResponse):
            raise DecisionAuthorityUnavailable("unverified Platform transport response")
        if response.status_code == 403:
            raise DecisionScopeDenied("current Project membership denied")
        if (
            response.status_code != 200
            or response.content_type.split(";", 1)[0] != "application/json"
            or not isinstance(response.body, bytes)
            or not 1 <= len(response.body) <= _MAX_BODY
        ):
            raise DecisionAuthorityUnavailable("current Platform membership proof unavailable")
        try:
            current = _CurrentMember.model_validate(load_authority_json(response.body))
        except (ValueError, ValidationError):
            raise DecisionAuthorityUnavailable("Platform owner response invalid") from None
        now = datetime.now(UTC)
        if (
            current.issuer != rauthy_issuer
            or current.subject != rauthy_subject
            or current.project_uuid != project_uuid
            or current.actor_uuid.version != 4
            or current.project_uuid.version != 4
            or current.expires_at.tzinfo is None
            or not now < current.expires_at <= delegation.expires_at
        ):
            raise DecisionScopeDenied("Platform membership mismatch or expired")
        return VerifiedProjectMembership(
            rauthy_issuer=rauthy_issuer,
            rauthy_subject=rauthy_subject,
            actor_uuid=current.actor_uuid,
            project_uuid=project_uuid,
            expires_at=current.expires_at,
        )
