from __future__ import annotations

from common.runtime_annotations import (
    DESTRUCTIVE_EXTERNAL,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
from common.runtime_common import build_private_mcp, management_client, private_http_app
from common.runtime_policy_contracts import GitHubRuntimePolicy
from common.settings import (
    GitHubPolicySettings,
    ManagementClientSettings,
    PrivateRuntimeSettings,
)

from .account_tools import register_github_account_tools
from .github_actions_tools import register_github_actions_tools
from .github_collab_tools import register_github_collab_tools
from .github_core_tools import register_github_core_tools
from .github_review_tools import register_github_review_tools
from .github_reviewer_tools import register_github_reviewer_tools
from .github_tools import register_github_workflow_tools
from .tool_context import GitHubRuntimeContext
from .workflow_guard import GitHubLocalFirstMiddleware

_private_settings = PrivateRuntimeSettings()
_management = management_client(ManagementClientSettings())
_policy = GitHubPolicySettings()
_context = GitHubRuntimeContext(_management, _policy)

mcp = build_private_mcp("github", _management)


def _github_runtime_policy() -> GitHubRuntimePolicy:
    try:
        return _management.github_runtime_policy()
    except Exception:
        return GitHubRuntimePolicy()


mcp.middleware.insert(0, GitHubLocalFirstMiddleware(_github_runtime_policy))

register_github_account_tools(
    mcp,
    _context.list_accounts,
    _context.account_capabilities,
    READ_EXTERNAL,
)
register_github_core_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
    _github_runtime_policy,
)
register_github_workflow_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)
register_github_review_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
register_github_collab_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
register_github_actions_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)
register_github_reviewer_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)

app = private_http_app(mcp, _private_settings)
