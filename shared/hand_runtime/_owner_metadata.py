"""Optional owner-bound read-only metadata tools for non-Files MCP Hands.

NO privileged legacy provider is imported. This source-only construction
requires SDK-verified resource JWT, private Cedar and owner-backed inspection.
The deployed Hand servers never import or call this optional factory.

The existing V2 Cedar action words are conservative umbrellas here, NOT an
accepted read-only policy grant. Backend must approve a narrower vocabulary
before any activation. Scope selectors never grant access by themselves.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from starlette.applications import Starlette

from ._diagnostics import ProtectedHandTools
from ._effect_auth import (
    EffectAuthorizationMiddleware,
    ResolvedEffect,
    ToolEffectBinding,
    TrustedPrivateDecisionPort,
)
from ._hand_app import create_diagnostic_hand_app

_HANDLE = re.compile(r"[a-z0-9][a-z0-9_-]{0,95}\Z", re.ASCII)
_STATE = frozenset({"active", "inactive", "degraded", "unknown"})
_MAX_REVISION = 2**63 - 1

# Fixed by Runtime, not chosen by an MCP request or an ENV variable.
# New read-only Cedar actions require Backend policy/schema agreement;
# until then even these more privileged existing action words may NOT be
# used as proof of a read-only product grant.
_SPECS: dict[str, tuple[str, str, str]] = {
    "terminal": ("workspace_metadata", "terminal.execute", "workspace"),
    "svc": ("repository_metadata", "integrations.use", "repository"),
    "infrastructure": ("application_metadata", "integrations.use", "application"),
    "reverse": ("analysis_project_metadata", "analysis.import", "analysis_project"),
}


@dataclass(frozen=True, slots=True)
class MetadataInspection:
    """Untrusted command shape plus SDK-verified, short-lived caller context."""

    bearer: str = field(repr=False)
    project_uuid: UUID
    agent_session_uuid: UUID
    grant_revision: int
    resource_handle: str
    action: str
    resource_kind: str


@dataclass(frozen=True, slots=True)
class ResourceMetadata:
    """Bounded, deliberately sparse owner response. Never arbitrary JSON."""

    state: Literal["active", "inactive", "degraded", "unknown"]
    revision: int


class TrustedMetadataOwnerPort(Protocol):
    async def inspect(self, request: MetadataInspection) -> ResourceMetadata:
        """Reverify caller, current Project/grant, mapping and resource lease.

        No caller-provided path, browser, process, account or ENV may supply
        the resource owner. The owner MUST check that the resource handle
        resolves to the same kind/action/Project that Cedar authorized.
        """
        ...


@dataclass(frozen=True, slots=True)
class TrustedMetadataPorts:
    effect_resolver: Callable[[dict[str, Any]], Awaitable[ResolvedEffect]]
    private_decision: TrustedPrivateDecisionPort
    owner: TrustedMetadataOwnerPort

    def __post_init__(self) -> None:
        if not all(
            callable(part)
            for part in (
                self.effect_resolver,
                getattr(self.private_decision, "decide", None),
                getattr(self.owner, "inspect", None),
            )
        ):
            raise ValueError("metadata Hand requires all independently trusted owner ports")


def _authenticated_request(resource_handle: str, *, action: str, kind: str) -> MetadataInspection:
    if not isinstance(resource_handle, str) or _HANDLE.fullmatch(resource_handle) is None:
        raise ValueError("invalid metadata handle")
    # One Hand-wide verified resource JWT is still NOT permission: selectors
    # remain bound to the original request and are owner-rechecked per call.
    bearer, http = EffectAuthorizationMiddleware._verified_request()
    project, session, revision = EffectAuthorizationMiddleware._request_selectors(http)
    return MetadataInspection(bearer, project, session, revision, resource_handle, action, kind)


def _sanitize_owner_metadata(value: ResourceMetadata) -> dict[str, str | int]:
    if (
        type(value) is not ResourceMetadata
        or value.state not in _STATE
        or type(value.revision) is not int
        or not 1 <= value.revision <= _MAX_REVISION
    ):
        raise ValueError("metadata owner returned an invalid bounded response")
    return {"state": value.state, "revision": value.revision}


def build_protected_metadata_app(
    *,
    hand: str,
    source_root: Path,
    ports: TrustedMetadataPorts,
) -> Starlette:
    """Stage one nonmutating owner lookup; default public Hand stays unchanged."""
    if hand not in _SPECS or type(ports) is not TrustedMetadataPorts:
        raise ValueError("not a supported owner-bound metadata Hand")
    tool_name, action, kind = _SPECS[hand]

    def register(mcp: FastMCP) -> None:
        @mcp.tool(
            name=tool_name,
            title=f"Read Project-owned {kind} status",
            annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
            run_in_thread=False,
        )
        async def read_metadata(resource_handle: str) -> dict[str, str | int]:
            try:
                original = _authenticated_request(resource_handle, action=action, kind=kind)
                # A verified owner response is not permanent: the fresh owner
                # inspection must independently recheck current grant/lease.
                metadata = await asyncio.wait_for(ports.owner.inspect(original), timeout=3)
                result = _sanitize_owner_metadata(metadata)
                if _authenticated_request(resource_handle, action=action, kind=kind) != original:
                    raise ValueError("original caller or selectors changed during owner inspection")
                return result
            except asyncio.CancelledError:
                raise
            except Exception:
                # Prevent tokens/UUIDs/provider errors/metadata from leaking
                # through FastMCP's user-visible error channel.
                raise ToolError("MCP_METADATA_OWNER_UNAVAILABLE") from None

    return create_diagnostic_hand_app(
        hand=hand,
        source_root=source_root,
        unavailable_code=f"{hand.upper()}_OAUTH_AUTHORIZATION_UNAVAILABLE",
        health_fields={"authorization": "owner_ports_injected_unaccepted"},
        protected_tools=ProtectedHandTools(
            register=register,
            effect_bindings={tool_name: ToolEffectBinding(action, kind, ports.effect_resolver)},
            private_decision=ports.private_decision,
        ),
    )
