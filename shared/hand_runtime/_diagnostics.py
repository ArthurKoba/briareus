"""Diagnostic MCP and explicit, independently guarded owner tool injection.

The default runtime exposes only bounded read-only diagnostics. Protected
tools require an explicit trusted composition root and a signed resource
verifier; no provider credential, workspace root or permit is manufactured.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier

from ._effect_auth import (
    EffectAuthorizationMiddleware,
    ToolEffectBinding,
    TrustedPrivateDecisionPort,
)


@dataclass(frozen=True, slots=True)
class ProtectedHandTools:
    """Trusted composition-root registration; never browser/ENV payload.

    The application owner supplies real authenticated private ports, tool
    bindings and a registrar together. This dataclass does not create a
    service credential, a Files root, or an Authorization decision.
    """

    register: Callable[[FastMCP], None]
    effect_bindings: Mapping[str, ToolEffectBinding]
    private_decision: TrustedPrivateDecisionPort

    def __post_init__(self) -> None:
        if (
            not callable(self.register)
            or not self.effect_bindings
            or not callable(getattr(self.private_decision, "decide", None))
        ):
            raise ValueError("protected Hand registration requires explicit trusted ports")


def diagnostic_mcp(
    hand: str,
    catalog: dict[str, object],
    *,
    resource_verifier: JWTVerifier | None = None,
    protected_tools: ProtectedHandTools | None = None,
) -> FastMCP:
    """Build diagnostic MCP; optional signed resource admission remains closed."""
    if protected_tools is not None and resource_verifier is None:
        raise ValueError("protected Hand requires a signed Rauthy resource verifier")
    mcp = FastMCP(f"briareus-{hand}-diagnostics", auth=resource_verifier)
    # Missing OAuth configuration never removes the per-effect PEP.
    # An accidentally registered protected tool must still fail closed.
    mcp.add_middleware(
        EffectAuthorizationMiddleware(
            hand,
            effect_bindings=protected_tools.effect_bindings if protected_tools else None,
            private_decision=protected_tools.private_decision if protected_tools else None,
        )
    )
    declared_count = int(catalog["declared_tool_count"])
    tools = catalog["declared_tools"]
    assert isinstance(tools, list)
    groups = Counter(
        str(item["module"]).split(".")[1]
        for item in tools
        if isinstance(item, dict) and isinstance(item.get("module"), str)
    )

    @mcp.tool(
        title="Hand runtime status",
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    )
    def hand_status() -> dict[str, object]:
        """Report process-level MCP diagnostics, not tool execution readiness."""
        return {
            "hand": hand,
            "transport": "resource_auth_staged" if resource_verifier else "diagnostic_only",
            "authorization": "resource_verifier_configured"
            if resource_verifier
            else "not_configured",
            "protected_execution": (
                "owner_ports_injected_unaccepted" if protected_tools else "disabled"
            ),
            "declared_legacy_tool_count": declared_count,
            "registered_diagnostic_tools": 2,
            "ready": False,
        }

    @mcp.tool(
        title="Hand source tool summary",
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    )
    def hand_source_summary() -> dict[str, object]:
        """Summarize copied source declarations without activating them."""
        return {
            "hand": hand,
            "declared_legacy_tool_count": declared_count,
            "source_modules": dict(sorted(groups.items())),
            "source_declarations_are_callable": False,
        }

    if resource_verifier is not None:

        @mcp.tool(
            title="Current Hand permission proof",
            annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
        )
        def hand_permission_probe() -> dict[str, object]:
            """Probe only action-level decision, never a resource or business effect."""
            return {
                "hand": hand,
                "authorization": "action_only_decision",
                "resource_scope_verified": False,
                "protected_execution": (
                    "owner_ports_injected_unaccepted" if protected_tools else "disabled"
                ),
            }

    if protected_tools is not None:
        # The middleware was installed FIRST, so any tool not in the immutable
        # binding map is rejected even if a registrar later adds it by mistake.
        protected_tools.register(mcp)
    return mcp
