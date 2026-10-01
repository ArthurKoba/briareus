from __future__ import annotations

from common.runtime_annotations import DESTRUCTIVE_LOCAL, READ_ONLY_LOCAL, WRITE_LOCAL
from common.runtime_common import build_private_mcp, management_client, private_http_app
from common.settings import FileSettings, ManagementClientSettings, PrivateRuntimeSettings

from .file_tools import register_file_tools
from .workspace_store import WorkspaceFileStore

_private_settings = PrivateRuntimeSettings()
_management = management_client(ManagementClientSettings())
_file_settings = FileSettings()

mcp = build_private_mcp("files", _management)
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
