"""Minimal Authorization owner policy vocabulary; no legacy runtime imports.

Gateway is connection-only; Hands require exact per-effect resource scope.
Do not import Identity, Resources SQL, or a legacy ServiceIdentityAuthority
merely to validate an authenticated service audience.
"""

from __future__ import annotations

ALLOWED_AUDIENCES = frozenset(
    {
        "gateway",
        "files",
        "terminal",
        "web",
        "reverse",
        "svc",
        "infrastructure",
    }
)
# Audience and operation MUST be checked as a pair. A signed Files caller
# cannot request Terminal execution merely because its human has that grant.
ACTION_AUDIENCES: dict[str, frozenset[str]] = {
    "files.read": frozenset({"files"}),
    "files.write": frozenset({"files"}),
    "project.metadata.read": frozenset({"gateway"}),
    "terminal.execute": frozenset({"terminal"}),
    "web.access": frozenset({"web"}),
    "analysis.import": frozenset({"reverse"}),
    "agents.manage": frozenset({"gateway"}),
    "integrations.use": frozenset({"svc", "infrastructure"}),
    "variables.use": frozenset({"svc", "infrastructure"}),
}


# V2 Hand-specific protected effects, source-aligned with Runtime's six
# Hand PEPs. Legacy management/project metadata actions are NOT MCP
# Hand effects and may not gain authority by borrowing the Gateway peer.
HAND_EFFECT_ACTIONS: dict[str, frozenset[str]] = {
    "files": frozenset({"files.read", "files.write"}),
    "terminal": frozenset({"terminal.execute"}),
    "web": frozenset({"web.access"}),
    "svc": frozenset({"integrations.use", "variables.use"}),
    "reverse": frozenset({"analysis.import"}),
    "infrastructure": frozenset({"integrations.use", "variables.use"}),
}
HAND_EFFECT_AUDIENCES: dict[str, frozenset[str]] = {
    action: frozenset(hand for hand, effects in HAND_EFFECT_ACTIONS.items() if action in effects)
    for action in frozenset().union(*HAND_EFFECT_ACTIONS.values())
}
