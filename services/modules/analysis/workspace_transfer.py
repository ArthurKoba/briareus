from __future__ import annotations

import base64
import uuid
from contextlib import suppress
from pathlib import Path

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport

from common.mcp_client_pool import PersistentMcpClientPool
from common.models import JsonObject, json_object
from common.settings import AnalysisSettings
from modules.files.workspace_store import WorkspaceFileStore

from .result import decode_call_result


class AnalysisTransferError(RuntimeError):
    pass


class AnalysisWorkspaceTransfers:
    """Import from shared storage and export generated artifacts back to it."""

    def __init__(
        self,
        settings: AnalysisSettings,
        workspace: WorkspaceFileStore,
        *,
        max_file_bytes: int,
        chunk_bytes: int = 1024 * 1024,
    ) -> None:
        self.settings = settings
        self.workspace = workspace
        self.max_file_bytes = max_file_bytes
        self.chunk_bytes = chunk_bytes
        self._backend_pool = PersistentMcpClientPool(
            self._client,
            name="analysis-transfer-ghidra",
            size=2,
        )

    def _client(self) -> Client[StreamableHttpTransport]:
        transport = StreamableHttpTransport(
            self.settings.backend_url,
            headers={"X-Koba-Proxy-Origin": "analysis"},
        )
        return Client(transport)

    async def _call(self, name: str, arguments: JsonObject) -> JsonObject:
        result = await self._backend_pool.call_tool(name, arguments)
        decoded = decode_call_result(result)
        if not isinstance(decoded, dict):
            raise AnalysisTransferError(
                f"analysis backend {name} returned no structured result"
            )
        value = json_object(decoded, context=f"analysis backend {name} result")
        error = value.get("error")
        if isinstance(error, str) and error.strip():
            raise AnalysisTransferError(error.strip())
        if value.get("success") is False:
            raise AnalysisTransferError(f"analysis backend {name} failed")
        return value

    def _workspace_import_source(
        self,
        workspace_path: str,
    ) -> JsonObject:
        source = self.workspace.path_for(workspace_path)
        if not source.is_file():
            raise AnalysisTransferError(
                "workspace path is not a file; place the artifact in Files/Terminal "
                "shared storage before importing it"
            )
        size = source.stat().st_size
        if size > self.max_file_bytes:
            raise AnalysisTransferError("workspace file exceeds configured size limit")
        return {
            "path": source.as_posix(),
            "workspace_path": workspace_path,
            "size_bytes": size,
            "sha256": self.workspace.sha256(workspace_path),
        }

    async def import_workspace_file(
        self,
        project_id: str,
        workspace_path: str,
        project_folder: str = "/",
        language: str = "",
        compiler_spec: str = "",
        auto_analyze: bool = True,
    ) -> JsonObject:
        source = self._workspace_import_source(workspace_path)
        result = await self._call(
            "import_file",
            {
                "project_id": project_id,
                "file_path": source["path"],
                "project_folder": project_folder,
                "language": language,
                "compiler_spec": compiler_spec,
                "auto_analyze": auto_analyze,
            },
        )
        return {
            "workspace_path": workspace_path,
            "sha256": source["sha256"],
            "size_bytes": source["size_bytes"],
            "result": result,
        }

    async def import_workspace_program(
        self,
        project_id: str,
        workspace_path: str,
        target_folder: str = "/",
        target_name: str = "",
        overwrite: bool = False,
    ) -> JsonObject:
        source = self._workspace_import_source(workspace_path)
        result = await self._call(
            "import_program",
            {
                "project_id": project_id,
                "gzf_path": source["path"],
                "target_folder": target_folder,
                "target_name": target_name,
                "overwrite": overwrite,
            },
        )
        return {
            "workspace_path": workspace_path,
            "sha256": source["sha256"],
            "size_bytes": source["size_bytes"],
            "result": result,
        }

    async def restore_workspace_project(
        self,
        project_id: str,
        workspace_path: str,
        project_name: str,
        parent_dir: str = "",
    ) -> JsonObject:
        source = self._workspace_import_source(workspace_path)
        result = await self._call(
            "restore_project",
            {
                "project_id": project_id,
                "gar_path": source["path"],
                "project_name": project_name,
                "parent_dir": parent_dir,
            },
        )
        return {
            "workspace_path": workspace_path,
            "sha256": source["sha256"],
            "size_bytes": source["size_bytes"],
            "result": result,
        }

    async def _copy_artifact_to_workspace(
        self,
        project_id: str,
        artifact_path: str,
        workspace_path: str,
        *,
        overwrite: bool,
    ) -> JsonObject:
        target = self.workspace.target_path(workspace_path)
        if target.exists() and not overwrite:
            raise AnalysisTransferError(
                f"workspace destination already exists: {workspace_path}"
            )
        if target.exists() and target.is_dir():
            raise AnalysisTransferError("workspace destination is a directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / (
            f".{target.name}.analysis-transfer-{uuid.uuid4().hex}.part"
        )
        temporary.unlink(missing_ok=True)

        offset = 0
        size_bytes: int | None = None
        try:
            with temporary.open("xb") as handle:
                while True:
                    chunk = await self._call(
                        "artifact_file_read",
                        {
                            "project_id": project_id,
                            "path": artifact_path,
                            "offset": offset,
                            "length": self.chunk_bytes,
                        },
                    )
                    raw = chunk.get("data_base64")
                    if not isinstance(raw, str):
                        raise AnalysisTransferError(
                            "analysis artifact read returned invalid data"
                        )
                    try:
                        data = base64.b64decode(raw, validate=True)
                    except Exception as exc:
                        raise AnalysisTransferError(
                            "analysis artifact read returned invalid base64"
                        ) from exc
                    handle.write(data)
                    next_offset = chunk.get("next_offset")
                    if not isinstance(next_offset, int) or next_offset < offset:
                        raise AnalysisTransferError(
                            "analysis artifact read returned invalid offset"
                        )
                    if data and next_offset <= offset:
                        raise AnalysisTransferError(
                            "analysis artifact read did not advance offset"
                        )
                    offset = next_offset
                    raw_size = chunk.get("size_bytes")
                    if isinstance(raw_size, int):
                        size_bytes = raw_size
                        if raw_size > self.max_file_bytes:
                            raise AnalysisTransferError(
                                "analysis artifact exceeds configured size limit"
                            )
                    if chunk.get("eof") is True:
                        break
                handle.flush()
            if size_bytes is not None and offset != size_bytes:
                raise AnalysisTransferError(
                    "analysis artifact transfer ended at unexpected size"
                )
            if target.exists():
                target.unlink()
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

        info = self.workspace.info(workspace_path)
        info["sha256"] = self.workspace.sha256(workspace_path)
        info["source_artifact_path"] = artifact_path
        cleanup_error = ""
        try:
            await self._call(
                "artifact_file_delete",
                {"project_id": project_id, "path": artifact_path},
            )
            info["source_deleted"] = True
        except Exception as exc:
            cleanup_error = str(exc)
            info["source_deleted"] = False
        info["source_cleanup_error"] = cleanup_error
        return info

    async def export_program_to_workspace(
        self,
        project_id: str,
        program_name: str,
        workspace_path: str,
        *,
        overwrite: bool = False,
    ) -> JsonObject:
        output_name = f"{uuid.uuid4().hex}-{Path(workspace_path).name}"
        exported = await self._call(
            "export_program",
            {
                "project_id": project_id,
                "program_name": program_name,
                "output_dir": "/artifacts/exports",
                "output_name": output_name,
            },
        )
        artifact_path = exported.get("path") or exported.get("output_path")
        if not isinstance(artifact_path, str) or not artifact_path:
            raise AnalysisTransferError(
                "analysis export did not return an artifact path"
            )
        return await self._copy_artifact_to_workspace(
            project_id,
            artifact_path,
            workspace_path,
            overwrite=overwrite,
        )

    async def archive_project_to_workspace(
        self,
        project_id: str,
        workspace_path: str,
        *,
        overwrite: bool = False,
    ) -> JsonObject:
        output_name = f"{uuid.uuid4().hex}-{Path(workspace_path).name}"
        archived = await self._call(
            "archive_project",
            {
                "project_id": project_id,
                "output_dir": "/artifacts/exports",
                "output_name": output_name,
            },
        )
        artifact_path = archived.get("path") or archived.get("output_path")
        if not isinstance(artifact_path, str) or not artifact_path:
            raise AnalysisTransferError(
                "analysis project archive did not return an artifact path"
            )
        return await self._copy_artifact_to_workspace(
            project_id,
            artifact_path,
            workspace_path,
            overwrite=overwrite,
        )


def register_workspace_transfer_tools(
    mcp: FastMCP,
    transfers: AnalysisWorkspaceTransfers,
) -> None:
    @mcp.tool(title="Import workspace file")
    async def import_workspace_file(
        project_id: str,
        workspace_path: str,
        project_folder: str = "/",
        language: str = "",
        compiler_spec: str = "",
        auto_analyze: bool = True,
    ) -> JsonObject:
        """Import an existing shared-workspace file without re-uploading its bytes."""
        return await transfers.import_workspace_file(
            project_id,
            workspace_path,
            project_folder,
            language,
            compiler_spec,
            auto_analyze,
        )

    @mcp.tool(title="Import workspace program package")
    async def import_workspace_program(
        project_id: str,
        workspace_path: str,
        target_folder: str = "/",
        target_name: str = "",
        overwrite: bool = False,
    ) -> JsonObject:
        """Import an existing workspace program package without re-uploading its bytes."""
        return await transfers.import_workspace_program(
            project_id,
            workspace_path,
            target_folder,
            target_name,
            overwrite,
        )

    @mcp.tool(title="Restore workspace project archive")
    async def restore_workspace_project(
        project_id: str,
        workspace_path: str,
        project_name: str,
        parent_dir: str = "",
    ) -> JsonObject:
        """Restore an existing workspace project archive without re-uploading its bytes."""
        return await transfers.restore_workspace_project(
            project_id,
            workspace_path,
            project_name,
            parent_dir,
        )

    @mcp.tool(title="Export program to workspace")
    async def export_program_to_workspace(
        project_id: str,
        program_name: str,
        workspace_path: str,
        overwrite: bool = False,
    ) -> JsonObject:
        """Export one analysis program into a normal shared-workspace file."""
        return await transfers.export_program_to_workspace(
            project_id,
            program_name,
            workspace_path,
            overwrite=overwrite,
        )

    @mcp.tool(title="Archive project to workspace")
    async def archive_project_to_workspace(
        project_id: str,
        workspace_path: str,
        overwrite: bool = False,
    ) -> JsonObject:
        """Archive an analysis project into a normal shared-workspace file."""
        return await transfers.archive_project_to_workspace(
            project_id,
            workspace_path,
            overwrite=overwrite,
        )
