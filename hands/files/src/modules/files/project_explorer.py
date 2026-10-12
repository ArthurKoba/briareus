"""Private Project Files explorer/upload/download application presentation.

This is a source contract, NOT an HTTP route or FastMCP tool. The accepted A4
Admin API defines no authenticated Project Files URL/DTO. Backend/Frontend B7
can later align a real C1-B2 endpoint to this bounded read/write projection;
no caller identity, credential, disk descriptor or raw container path is
serialized into its results.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from typing import Literal, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from modules.project_runtime import ProjectInvocation

from .project_files import ProjectFilesService
from .project_workspace import ProjectFileEntry, ProjectFilePage


class ProjectExplorerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ProjectFileMetadata(ProjectExplorerModel):
    path: str
    kind: Literal["file", "directory"]
    size_bytes: int = Field(ge=0)
    modified_at_ns: int = Field(ge=0)

    @classmethod
    def from_entry(cls, entry: ProjectFileEntry) -> ProjectFileMetadata:
        if entry.kind not in {"file", "directory"}:
            raise ProjectExplorerUnavailable("FILE_ENTRY_KIND_UNSUPPORTED")
        return cls(
            path=entry.path,
            kind=cast(Literal["file", "directory"], entry.kind),
            size_bytes=entry.size_bytes,
            modified_at_ns=entry.modified_at_ns,
        )


class ProjectDirectoryPage(ProjectExplorerModel):
    entries: tuple[ProjectFileMetadata, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=1000)

    @classmethod
    def from_page(cls, page: ProjectFilePage) -> ProjectDirectoryPage:
        return cls(
            entries=tuple(ProjectFileMetadata.from_entry(entry) for entry in page.entries),
            total=page.total,
            offset=page.offset,
            limit=page.limit,
        )


class ProjectDownloadChunk(ProjectExplorerModel):
    """One bounded Base64 transfer chunk from an immutable private snapshot."""

    path: str
    offset: int = Field(ge=0)
    size_bytes: int = Field(ge=0, le=1024 * 1024)
    total_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_base64: str
    eof: bool


class ProjectUploadRequest(ProjectExplorerModel):
    destination: str = Field(min_length=1, max_length=4096)
    operation_uuid: UUID
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("operation_uuid", mode="before")
    @classmethod
    def uuidv4(cls, value: object) -> UUID:
        # JSON requests carry UUID text; strict Python models do not coerce.
        if isinstance(value, UUID):
            parsed = value
        elif isinstance(value, str) and len(value) == 36:
            try:
                parsed = UUID(value)
            except ValueError as exc:
                raise ValueError("Project upload UUID must be canonical") from exc
            if str(parsed) != value:
                raise ValueError("Project upload UUID must be canonical")
        else:
            raise ValueError("Project upload UUID must be canonical")
        if parsed.version != 4:
            raise ValueError("Project upload operation UUID must be v4")
        return parsed


class ProjectUploadReceipt(ProjectExplorerModel):
    operation_uuid: UUID
    path: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["committed"] = "committed"


class ProjectExplorerUnavailable(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ProjectExplorerPort(Protocol):
    async def list_directory(
        self,
        invocation: ProjectInvocation,
        *,
        path: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> ProjectDirectoryPage: ...

    async def metadata(
        self, invocation: ProjectInvocation, *, path: str
    ) -> ProjectFileMetadata: ...

    def download_chunks(
        self,
        invocation: ProjectInvocation,
        *,
        path: str,
        chunk_bytes: int = 1024 * 1024,
    ) -> AsyncIterator[ProjectDownloadChunk]: ...

    async def upload_stream(
        self,
        invocation: ProjectInvocation,
        *,
        request: ProjectUploadRequest,
        chunks: AsyncIterator[bytes],
    ) -> ProjectUploadReceipt: ...


class ProjectFileExplorer:
    """Private, project-aware use cases with no unauthenticated file handles."""

    def __init__(self, files: ProjectFilesService) -> None:
        self.files = files

    async def list_directory(
        self,
        invocation: ProjectInvocation,
        *,
        path: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> ProjectDirectoryPage:
        page = await self.files.list(invocation, path, offset=offset, limit=limit)
        return ProjectDirectoryPage.from_page(page)

    async def metadata(self, invocation: ProjectInvocation, *, path: str) -> ProjectFileMetadata:
        return ProjectFileMetadata.from_entry(await self.files.info(invocation, path))

    async def download_chunks(
        self,
        invocation: ProjectInvocation,
        *,
        path: str,
        chunk_bytes: int = 1024 * 1024,
    ) -> AsyncIterator[ProjectDownloadChunk]:
        if not 0 < chunk_bytes <= 1024 * 1024:
            raise ProjectExplorerUnavailable("FILE_DOWNLOAD_CHUNK_INVALID")
        async with self.files.open_snapshot(invocation, path, chunk_bytes=chunk_bytes) as snap:
            offset = 0
            if not snap.size_bytes:
                # Even an empty file must re-check current actor/Project read
                # rights before exposing hash/metadata to a client.
                await self.files.read_snapshot_chunk(invocation, snap, offset=0, length=chunk_bytes)
                yield ProjectDownloadChunk(
                    path=path,
                    offset=0,
                    size_bytes=0,
                    total_bytes=0,
                    sha256=snap.sha256,
                    data_base64="",
                    eof=True,
                )
            while offset < snap.size_bytes:
                data = await self.files.read_snapshot_chunk(
                    invocation, snap, offset=offset, length=chunk_bytes
                )
                if not data:
                    raise ProjectExplorerUnavailable("FILE_SNAPSHOT_TRUNCATED")
                next_offset = offset + len(data)
                yield ProjectDownloadChunk(
                    path=path,
                    offset=offset,
                    size_bytes=len(data),
                    total_bytes=snap.size_bytes,
                    sha256=snap.sha256,
                    data_base64=base64.b64encode(data).decode("ascii"),
                    eof=next_offset == snap.size_bytes,
                )
                offset = next_offset

    async def upload_stream(
        self,
        invocation: ProjectInvocation,
        *,
        request: ProjectUploadRequest,
        chunks: AsyncIterator[bytes],
    ) -> ProjectUploadReceipt:
        entry = await self.files.write_stream(
            invocation,
            request.destination,
            chunks,
            expected_size=request.size_bytes,
            expected_sha256=request.sha256,
            operation_uuid=request.operation_uuid,
        )
        if entry.kind != "file" or entry.size_bytes != request.size_bytes:
            raise ProjectExplorerUnavailable("FILE_UPLOAD_RESULT_UNCERTAIN")
        return ProjectUploadReceipt(
            operation_uuid=request.operation_uuid,
            path=entry.path,
            size_bytes=entry.size_bytes,
            sha256=request.sha256,
        )
