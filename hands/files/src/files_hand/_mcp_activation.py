"""Optional trusted composition root for the first native Files MCP read.

The deployed files_hand.server intentionally never calls this factory.
Only a supervisor that has independently authenticated each port and a
real Rauthy resource audience may construct a protected Files Hand.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from hand_runtime import (
    ProtectedHandTools,
    ResolvedEffect,
    ToolEffectBinding,
    TrustedPrivateDecisionPort,
    create_diagnostic_hand_app,
)
from starlette.applications import Starlette

from ._mcp_request import stage_untrusted_native_read
from ._native_read import UnmountedNativeFilesRead
from ._read_authority import BoundFilesReadAuthority, TrustedFilesRootPort, TrustedReadChannelPort


@dataclass(frozen=True, slots=True)
class TrustedFilesReadPorts:
    """Runtime-supplied, independently verified peers, never MCP arguments."""

    effect_resolver: Callable[[dict[str, Any]], Awaitable[ResolvedEffect]]
    private_decision: TrustedPrivateDecisionPort
    read_channels: TrustedReadChannelPort
    roots: TrustedFilesRootPort

    def __post_init__(self) -> None:
        if not all(
            callable(value)
            for value in (
                self.effect_resolver,
                getattr(self.private_decision, "decide", None),
                getattr(self.read_channels, "open_channel", None),
                getattr(self.roots, "hold_root", None),
            )
        ):
            raise ValueError("signed Files read needs all independent trusted owner ports")


def build_protected_files_app(ports: TrustedFilesReadPorts) -> Starlette:
    """Prepare an explicitly injected, still fail-closed native Files Hand.

    This constructor neither mints a token nor provisions a Files root. A
    non-configured Rauthy resource verifier is rejected by the shared
    factory BEFORE a protected tool is installed. The generic Hand
    middleware checks signed identity, immutable owner effect arguments
    and fresh Cedar permission. BoundFilesReadAuthority then performs its
    OWN original-token/current-root and two-phase Access revalidation.
    """
    if not isinstance(ports, TrustedFilesReadPorts):
        raise ValueError("trusted Files ports must be provided by the supervisor")

    reader = UnmountedNativeFilesRead(
        BoundFilesReadAuthority(channels=ports.read_channels, roots=ports.roots)
    )

    def register(mcp: FastMCP) -> None:
        @mcp.tool(
            name="read_file",
            title="Read a protected Project file",
            annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
            run_in_thread=False,
        )
        async def read_file(path: str, max_bytes: int = 262_144) -> dict[str, str | int]:
            try:
                request = stage_untrusted_native_read(
                    request=get_http_request(),
                    arguments={"path": path, "max_bytes": max_bytes},
                )
                result = await reader.execute(request)
                return result.content_payload()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Neither credentials, a server root, a private actor nor
                # a file path/bytes may escape on any owner/OS/peer failure.
                raise ToolError("FILES_READ_AUTHORIZATION_UNAVAILABLE") from None

    protected = ProtectedHandTools(
        register=register,
        effect_bindings={
            "read_file": ToolEffectBinding("files.read", "workspace_path", ports.effect_resolver)
        },
        private_decision=ports.private_decision,
    )
    return create_diagnostic_hand_app(
        hand="files",
        source_root=Path(__file__).resolve().parents[1],
        unavailable_code="FILES_OAUTH_AUTHORIZATION_UNAVAILABLE",
        health_fields={"authorization": "owner_ports_injected_unaccepted"},
        protected_tools=protected,
    )
