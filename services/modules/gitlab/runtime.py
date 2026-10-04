from __future__ import annotations

from common.runtime_annotations import (
    DESTRUCTIVE_EXTERNAL,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
from common.runtime_common import build_private_mcp, management_client, private_http_app
from common.runtime_policy_contracts import GitLabRuntimePolicy
from common.settings import (
    GitLabSettings,
    ManagementClientSettings,
    PrivateRuntimeSettings,
)

from .gitlab_tools import register_gitlab_tools
from .tool_context import GitLabRuntimeContext
from .workflow_guard import GitLabLocalFirstMiddleware

_private_settings = PrivateRuntimeSettings()
_management = management_client(ManagementClientSettings())
_context = GitLabRuntimeContext(_management, GitLabSettings())

mcp = build_private_mcp("gitlab", _management)


def _gitlab_runtime_policy() -> GitLabRuntimePolicy:
    try:
        return _management.gitlab_runtime_policy()
    except Exception:
        return GitLabRuntimePolicy()


mcp.middleware.insert(0, GitLabLocalFirstMiddleware(_gitlab_runtime_policy))

register_gitlab_tools(
    mcp,
    _context,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)

app = private_http_app(mcp, _private_settings)
