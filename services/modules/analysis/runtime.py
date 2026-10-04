from __future__ import annotations

from common.runtime_common import admin_api_client, build_private_mcp, private_http_app
from common.settings import (
    AdminApiClientSettings,
    AnalysisSettings,
    FileSettings,
    PrivateRuntimeSettings,
)
from modules.files.workspace_store import WorkspaceFileStore

from .provider import AnalysisToolProvider
from .workspace_transfer import AnalysisWorkspaceTransfers, register_workspace_transfer_tools

_private_settings = PrivateRuntimeSettings()
_admin_api = admin_api_client(AdminApiClientSettings())
_analysis_settings = AnalysisSettings()
_file_settings = FileSettings()
_workspace = WorkspaceFileStore(_file_settings.workspace_root)

mcp = build_private_mcp("analysis", _admin_api)
mcp.add_provider(AnalysisToolProvider(_analysis_settings))
register_workspace_transfer_tools(
    mcp,
    AnalysisWorkspaceTransfers(
        _analysis_settings,
        _workspace,
        max_file_bytes=_file_settings.upload_max_bytes,
    ),
)

app = private_http_app(mcp, _private_settings)
