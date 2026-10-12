"""Access-owned Cedar policy for current Project AgentSession grants.

Cedar decides based on a freshly loaded Authorization row, never a caller
assertion. The initial policy is code-owned and deliberately conservative.
Future MCP policy management may replace the policy set only through an
authenticated, versioned owner API, not ENV/client-provided Cedar text.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from authorization._cedar_policy import CedarOperation, CedarPolicyEvaluator, CurrentGrant
from authorization._session_persistence import ProjectAgentSessionRow

# Two explicit policy tiers; elevated rights can never be authorized by a
# normal AgentSession even if malformed/stale DB JSON lists those grants.
_BASELINE_POLICY = """
// Admission is only a connection-level check. The Hand separately evaluates
// the specific tool operation before every protected effect.
permit(principal is User, action == Action::"mcp.connect", resource is Project)
when { context.grantVersion >= 1 };

permit(principal is User,
       action in [Action::"files.read", Action::"project.metadata.read"],
       resource is Project)
when { context.grantVersion >= 1 };

permit(principal is User,
       action in [Action::"files.write", Action::"terminal.execute",
                  Action::"web.access", Action::"analysis.import",
                  Action::"agents.manage", Action::"integrations.use",
                  Action::"variables.use", Action::"integrations.manage",
                  Action::"variables.manage"],
       resource is Project)
when { context.grantVersion >= 1 && context.isElevated == true };
"""

_POLICY = CedarPolicyEvaluator(_BASELINE_POLICY)


def permits_current_project_grant(
    *,
    row: ProjectAgentSessionRow,
    actor_uuid: UUID,
    project_uuid: UUID,
    operation: str,
    expected_version: int,
) -> bool:
    """Deny absent, stale, revoked or actor-mismatched durable grants."""
    if (
        row.session_uuid is None
        or row.created_by_principal_id != actor_uuid
        or row.project_id != project_uuid
        or row.status != "active"
        or row.revoked_at is not None
        or row.version != expected_version
        or row.version < 1
        or not isinstance(row.grants, dict)
    ):
        return False
    operations = row.grants.get("operations")
    if (
        not isinstance(operations, list)
        or len(operations) > 32
        or not all(isinstance(value, str) and len(value) <= 128 for value in operations)
        or not operations
        or (operation != "mcp.connect" and operation not in operations)
    ):
        return False
    return _POLICY.permits(
        CedarOperation(
            actor_uuid=actor_uuid,
            agent_session_uuid=row.session_uuid,
            project_uuid=project_uuid,
            action=operation,
            resource_type="Project",
            resource_uuid=project_uuid,
        ),
        CurrentGrant(
            actor_uuid=row.created_by_principal_id,
            agent_session_uuid=row.session_uuid,
            project_uuid=row.project_id,
            action=operation,
            resource_uuid=project_uuid,
            active=row.status == "active" and row.revoked_at is None,
            expires_at=row.hard_expires_at,
            version=row.version,
            minimum_current_version=expected_version,
            is_elevated=row.is_elevated,
        ),
        now=datetime.now(UTC),
    )
