"""Public reusable components for independently deployed MCP Hands."""

from ._catalog import discover_source_tools, source_capabilities
from ._diagnostics import ProtectedHandTools
from ._effect_auth import (
    EffectAuthorizationMiddleware,
    PrivateDecisionReply,
    ResolvedEffect,
    ResourceTrust,
    ToolEffectBinding,
    TrustedPrivateDecisionPort,
)
from ._hand_app import create_diagnostic_hand_app
from ._owner_metadata import (
    MetadataInspection,
    ResourceMetadata,
    TrustedMetadataPorts,
    build_protected_metadata_app,
)

__all__ = [
    "EffectAuthorizationMiddleware",
    "MetadataInspection",
    "PrivateDecisionReply",
    "ProtectedHandTools",
    "ResolvedEffect",
    "ResourceMetadata",
    "ResourceTrust",
    "ToolEffectBinding",
    "TrustedMetadataPorts",
    "TrustedPrivateDecisionPort",
    "build_protected_metadata_app",
    "create_diagnostic_hand_app",
    "discover_source_tools",
    "source_capabilities",
]
