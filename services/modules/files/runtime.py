from __future__ import annotations

from common.runtime_annotations import DESTRUCTIVE_LOCAL, READ_ONLY_LOCAL, WRITE_LOCAL
from common.runtime_common import admin_api_client, build_private_mcp, private_http_app
from common.settings import AdminApiClientSettings, FileSettings, PrivateRuntimeSettings

from .file_tools import register_file_tools
from .workspace_store import WorkspaceFileStore

_private_settings = PrivateRuntimeSettings()
_admin_api = admin_api_client(AdminApiClientSettings())
_file_settings = FileSettings()

mcp = build_private_mcp("files", _admin_api)
_workspace = WorkspaceFileStore(_file_settings.workspace_root)

register_file_tools(
    mcp,
    READ_ONLY_LOCAL,
    WRITE_LOCAL,
    DESTRUCTIVE_LOCAL,
    workspace=_workspace,
    max_file_bytes=_file_settings.upload_max_bytes,
)

app = private_http_app(mcp, _private_settings)
