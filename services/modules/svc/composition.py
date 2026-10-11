"""Fail-closed GitHub/GitLab source selection for the private SVC owner.

This is not a public MCP transport, provider credential distributor, or an
in-process replacement for current Identity/Control/Access and C2 checks.
Only an independently accepted caller/source verifier can supply live ports.
The historical provider handlers remain in their owning modules unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from modules.project_runtime.authorization import (
    ProjectAccessDenied,
    ProjectInvocation,
    ProjectOwnerFence,
    ProjectPermit,
    ProjectRuntimeAuthority,
)

SVCProvider = Literal["github", "gitlab"]
SVCAction = Literal["svc.read", "svc.write"]

# Explicit service-owned source catalog, not a URL, credential or permissive
# wildcard. Both private handler families remain packaged by package_graph.
SVC_SOURCE_HANDLERS: dict[SVCProvider, tuple[str, str]] = {
    "github": ("modules.github.runtime", "mcp"),
    "gitlab": ("modules.gitlab.runtime", "mcp"),
}


def _uuid4(value: object) -> bool:
    return isinstance(value, UUID) and value.version == 4


class SVCUnavailable(ProjectAccessDenied):
    """No source-proven authorization to select or invoke an SVC handler."""


@dataclass(frozen=True, slots=True)
class VerifiedSVCPeer:
    """Result ONLY from an injected signed C2 and consumed-JTI verifier.

    Merely constructing these fields cannot establish network peer identity.
    Source composition has NO signer and cannot instantiate this port itself.
    """

    project_id: UUID
    actor_id: UUID
    session_uuid: UUID
    operation_uuid: UUID
    service_id: UUID
    instance_uuid: UUID
    consumed_jti: UUID
    recipient: Literal["svc"]
    provider: SVCProvider
    action: SVCAction
    original_idempotency_key: str
    source_owner_fence: ProjectOwnerFence
    expires_at: datetime


class TrustedSVCServiceSourcePort(Protocol):
    """Physical C2 service identity + original JTI consumption, not JSON."""

    async def require_current_service_source(
        self,
        invocation: ProjectInvocation,
        *,
        provider: SVCProvider,
        action: SVCAction,
    ) -> VerifiedSVCPeer: ...


@dataclass(frozen=True, slots=True)
class SVCSourceSelection:
    """Privately approved source label; NEVER a tool call or access token."""

    provider: SVCProvider
    module_name: str
    handler_name: Literal["mcp"]
    operation_uuid: UUID
    recipient_service_id: UUID
    recipient_instance_uuid: UUID


class PrivateSVCSourceSelector:
    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        *,
        service_source: TrustedSVCServiceSourcePort | None = None,
    ) -> None:
        self.authority = authority
        self.service_source = service_source

    async def require_source(
        self,
        invocation: ProjectInvocation,
        *,
        provider: SVCProvider,
        action: SVCAction,
    ) -> SVCSourceSelection:
        """Require real same-original current grant and C2 before selecting.

        Does NOT import provider runtime or call a tool: provider authorization,
        Catalog-custodied credential lease and real safe MCP forwarding are
        separately release-gated. No fallback to Admin API account selectors.
        """
        if provider not in SVC_SOURCE_HANDLERS or action not in {"svc.read", "svc.write"}:
            raise SVCUnavailable("SVC_PROVIDER_OR_ACTION_NOT_ACCEPTED")
        scope = invocation.operation_scope
        if (
            self.service_source is None
            or scope is None
            or scope.action != action
            or scope.project_id != invocation.project_id
            or scope.agent_session_uuid != invocation.session_uuid
            or not _uuid4(scope.request_uuid)
        ):
            raise SVCUnavailable("SVC_SIGNED_C2_OR_ORIGINAL_SCOPE_REQUIRED")
        initial = await self.authority.require(invocation, action)
        if (
            initial.owner_fence is None
            or not isinstance(initial.expires_at, datetime)
            or initial.expires_at.tzinfo is None
            or initial.expires_at.utcoffset() is None
            or initial.expires_at <= datetime.now(UTC)
        ):
            raise SVCUnavailable("SVC_THREE_OWNER_FENCE_REQUIRED")
        try:
            peer = await self.service_source.require_current_service_source(
                invocation, provider=provider, action=action
            )
        except Exception as exc:
            raise SVCUnavailable("SVC_SIGNED_SERVICE_SOURCE_UNAVAILABLE") from exc
        if (
            not isinstance(peer, VerifiedSVCPeer)
            or not all(
                _uuid4(value)
                for value in (
                    peer.project_id,
                    peer.actor_id,
                    peer.session_uuid,
                    peer.operation_uuid,
                    peer.service_id,
                    peer.instance_uuid,
                    peer.consumed_jti,
                )
            )
            or peer.recipient != "svc"
            or peer.provider != provider
            or peer.action != action
            or peer.project_id != initial.project_id
            or peer.actor_id != initial.actor_id
            or peer.session_uuid != initial.session_uuid
            or peer.operation_uuid != scope.request_uuid
            or peer.original_idempotency_key != str(scope.request_uuid)
            or peer.source_owner_fence != initial.owner_fence
            or not isinstance(peer.expires_at, datetime)
            or peer.expires_at.tzinfo is None
            or peer.expires_at.utcoffset() is None
            or peer.expires_at <= datetime.now(UTC)
            or peer.expires_at > initial.expires_at
        ):
            raise SVCUnavailable("SVC_VERIFIED_PEER_SCOPE_CHANGED")
        refreshed: ProjectPermit = await self.authority.require(invocation, action)
        if (
            refreshed.project_id != initial.project_id
            or refreshed.actor_id != initial.actor_id
            or refreshed.session_uuid != initial.session_uuid
            or refreshed.project_owner_id != initial.project_owner_id
            or refreshed.project_owner_scope != initial.project_owner_scope
            or refreshed.project_access_revision != initial.project_access_revision
            or refreshed.owner_fence != initial.owner_fence
            or refreshed.decision_version != initial.decision_version
            or not isinstance(refreshed.expires_at, datetime)
            or refreshed.expires_at.tzinfo is None
            or refreshed.expires_at.utcoffset() is None
            or refreshed.expires_at <= datetime.now(UTC)
            or peer.expires_at > refreshed.expires_at
            or peer.expires_at <= datetime.now(UTC)
        ):
            raise SVCUnavailable("SVC_CURRENT_GRANT_REVOKED")
        module_name, handler = SVC_SOURCE_HANDLERS[provider]
        if handler != "mcp":
            raise SVCUnavailable("SVC_SOURCE_HANDLER_NOT_REVIEWED")
        return SVCSourceSelection(
            provider=provider,
            module_name=module_name,
            handler_name="mcp",
            operation_uuid=scope.request_uuid,
            recipient_service_id=peer.service_id,
            recipient_instance_uuid=peer.instance_uuid,
        )
