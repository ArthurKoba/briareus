from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .models import ClientFile
from .workspace_ingress import ingest_workspace_file
from .workspace_store import WorkspaceFileStore


def register_file_tools(
    mcp: FastMCP,
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
    *,
    workspace: WorkspaceFileStore,
    max_file_bytes: int,
) -> None:
    @mcp.tool(title="File status", annotations=read_annotations)
    def file_status() -> JsonObject:
        return workspace.status()

    @mcp.tool(title="File list", annotations=read_annotations)
    def file_list(path: str = "", offset: int = 0, limit: int = 200) -> JsonObject:
        return workspace.list(path, offset=offset, limit=limit)

    @mcp.tool(title="File info", annotations=read_annotations)
    def file_info(path: str) -> JsonObject:
        return workspace.info(path)

    @mcp.tool(title="File read", annotations=read_annotations)
    def file_read(path: str, offset: int = 0, length: int = 1024 * 1024) -> JsonObject:
        return workspace.read(path, offset=offset, length=length)

    @mcp.tool(title="File hash", annotations=read_annotations)
    def file_hash(path: str) -> JsonObject:
        return {"path": path.strip().lstrip("/"), "sha256": workspace.sha256(path)}

    @mcp.tool(title="File write text", annotations=write_annotations)
    def file_write_text(
        path: str,
        content: str,
        overwrite: bool = True,
        create_parents: bool = True,
    ) -> JsonObject:
        return workspace.write_text(
            path, content, overwrite=overwrite, create_parents=create_parents
        )

    @mcp.tool(title="File write chunk", annotations=write_annotations)
    def file_write(
        path: str,
        data_base64: str,
        offset: int = 0,
        truncate: bool = False,
        create_parents: bool = True,
    ) -> JsonObject:
        return workspace.write_chunk(
            path,
            data_base64,
            offset=offset,
            truncate=truncate,
            create_parents=create_parents,
            max_file_bytes=max_file_bytes,
        )

    @mcp.tool(
        title="File ingest attachment",
        annotations=write_annotations,
        meta={"openai/fileParams": ["file"]},
    )
    def file_ingest(
        file: ClientFile,
        destination: str,
        expected_size: int | None = None,
        expected_sha256: str = "",
        overwrite: bool = False,
    ) -> JsonObject:
        return ingest_workspace_file(
            file=file,
            destination=destination,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            overwrite=overwrite,
            workspace=workspace,
            max_bytes=max_file_bytes,
        )

    @mcp.tool(title="File mkdir", annotations=write_annotations)
    def file_mkdir(path: str, parents: bool = True) -> JsonObject:
        return workspace.mkdir(path, parents=parents)

    @mcp.tool(title="File copy", annotations=write_annotations)
    def file_copy(source: str, destination: str, overwrite: bool = False) -> JsonObject:
        return workspace.copy(source, destination, overwrite=overwrite)

    @mcp.tool(title="File move", annotations=write_annotations)
    def file_move(source: str, destination: str, overwrite: bool = False) -> JsonObject:
        return workspace.move(source, destination, overwrite=overwrite)

    @mcp.tool(title="File delete", annotations=destructive_annotations)
    def file_delete(path: str, recursive: bool = False) -> JsonObject:
        return workspace.delete(path, recursive=recursive)
