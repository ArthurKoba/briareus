from __future__ import annotations

from common.runtime_annotations import (
    DESTRUCTIVE_EXTERNAL,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
from common.runtime_common import admin_api_client, build_private_mcp, private_http_app
from common.runtime_policy_contracts import GitLabRuntimePolicy
from common.settings import (
    AdminApiClientSettings,
    GitLabSettings,
    PrivateRuntimeSettings,
)

from .gitlab_tools import register_gitlab_tools
from .tool_context import GitLabRuntimeContext
from .workflow_guard import GitLabLocalFirstMiddleware

_private_settings = PrivateRuntimeSettings()
_admin_api = admin_api_client(AdminApiClientSettings())
_context = GitLabRuntimeContext(_admin_api, GitLabSettings())

mcp = build_private_mcp("gitlab", _admin_api)


def _gitlab_runtime_policy() -> GitLabRuntimePolicy:
    try:
        return _admin_api.gitlab_runtime_policy()
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
