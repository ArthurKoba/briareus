from __future__ import annotations

from common.runtime_annotations import (
    DESTRUCTIVE_LOCAL,
    READ_ONLY_LOCAL,
    WRITE_LOCAL,
)
from common.runtime_common import build_private_mcp, management_client, private_http_app
from common.settings import FileSettings, ManagementClientSettings, PrivateRuntimeSettings

from .file_store import FileStore
from .file_tools import register_file_tools
from .upload_manager import FileUploadManager
from .workspace_store import WorkspaceFileStore

_private_settings = PrivateRuntimeSettings()
_management = management_client(ManagementClientSettings())
_file_settings = FileSettings()

mcp = build_private_mcp("files", _management)
_store = FileStore(settings=_file_settings)
_upload_manager = FileUploadManager(_store)
_workspace = WorkspaceFileStore(_file_settings.workspace_root)

register_file_tools(
    mcp,
    READ_ONLY_LOCAL,
    WRITE_LOCAL,
    DESTRUCTIVE_LOCAL,
    store=_store,
    upload_manager=_upload_manager,
    workspace=_workspace,
)

app = private_http_app(mcp, _private_settings)
