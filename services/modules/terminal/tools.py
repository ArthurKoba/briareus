from __future__ import annotations

from fastmcp import FastMCP

from common.models import JsonObject
from common.runtime_annotations import (
    DESTRUCTIVE_EXTERNAL,
    DESTRUCTIVE_LOCAL,
    READ_ONLY_LOCAL,
    WRITE_LOCAL,
)

from .manager import TerminalManager


def register_terminal_tools(mcp: FastMCP, manager: TerminalManager) -> None:
    @mcp.tool(title="Terminal status", annotations=READ_ONLY_LOCAL)
    def terminal_status() -> JsonObject:
        """Report terminal runtime, workspace, job and toolchain status."""
        return manager.status()

    @mcp.tool(title="Workspace list", annotations=READ_ONLY_LOCAL)
    def workspace_list() -> JsonObject:
        """List persistent terminal workspaces."""
        return manager.workspace_list()

    @mcp.tool(title="Workspace create", annotations=WRITE_LOCAL)
    def workspace_create(workspace_id: str) -> JsonObject:
        """Create a persistent workspace directory."""
        return manager.workspace_create(workspace_id)

    @mcp.tool(title="Workspace info", annotations=READ_ONLY_LOCAL)
    def workspace_info(workspace_id: str) -> JsonObject:
        """Inspect one workspace and its jobs."""
        return manager.workspace_info(workspace_id)

    @mcp.tool(title="Workspace delete", annotations=DESTRUCTIVE_LOCAL)
    async def workspace_delete(workspace_id: str, force: bool = False) -> JsonObject:
        """Delete a workspace. Active jobs block deletion unless force=true."""
        return await manager.workspace_delete(workspace_id, force=force)

    @mcp.tool(title="Terminal exec", annotations=DESTRUCTIVE_EXTERNAL)
    async def terminal_exec(
        workspace_id: str,
        command: str,
        cwd: str = "",
        env: dict[str, str] | None = None,
        timeout_seconds: float = 60,
        max_output_bytes: int | None = None,
    ) -> JsonObject:
        """Run one bounded shell command inside a persistent workspace."""
        return await manager.terminal_exec(
            workspace_id,
            command,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )

    @mcp.tool(title="Job start", annotations=DESTRUCTIVE_EXTERNAL)
    async def job_start(
        workspace_id: str,
        command: str,
        cwd: str = "",
        env: dict[str, str] | None = None,
        interactive: bool = False,
        label: str = "",
        cols: int = 120,
        rows: int = 40,
        timeout_seconds: float | None = None,
    ) -> JsonObject:
        """Start a persistent long-running or interactive process job."""
        return await manager.job_start(
            workspace_id,
            command,
            cwd=cwd,
            env=env,
            interactive=interactive,
            label=label,
            cols=cols,
            rows=rows,
            timeout_seconds=timeout_seconds,
        )

    @mcp.tool(title="Job status", annotations=READ_ONLY_LOCAL)
    def job_status(job_id: str) -> JsonObject:
        """Read one job's process state and metadata."""
        return manager.job_status(job_id)

    @mcp.tool(title="Job list", annotations=READ_ONLY_LOCAL)
    def job_list(
        workspace_id: str = "",
        state: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> JsonObject:
        """List jobs with optional workspace/state filters and pagination."""
        return manager.job_list(
            workspace_id=workspace_id,
            state=state,
            offset=offset,
            limit=limit,
        )

    @mcp.tool(title="Job delete", annotations=DESTRUCTIVE_LOCAL)
    def job_delete(job_id: str) -> JsonObject:
        """Delete retained metadata/logs for a completed job."""
        return manager.job_delete(job_id)

    @mcp.tool(title="Job cleanup", annotations=DESTRUCTIVE_LOCAL)
    def job_cleanup(
        older_than_hours: int = 168,
        dry_run: bool = True,
        limit: int = 1000,
    ) -> JsonObject:
        """Preview or remove completed job logs older than a retention threshold."""
        return manager.job_cleanup(
            older_than_hours=older_than_hours,
            dry_run=dry_run,
            limit=limit,
        )

    @mcp.tool(title="Job read", annotations=READ_ONLY_LOCAL)
    async def job_read(
        job_id: str,
        cursor: int = 0,
        max_bytes: int | None = None,
        wait_seconds: float = 0,
    ) -> JsonObject:
        """Read only job output appended after cursor and return next_cursor."""
        return await manager.job_read(
            job_id,
            cursor=cursor,
            max_bytes=max_bytes,
            wait_seconds=wait_seconds,
        )

    @mcp.tool(title="Job write", annotations=DESTRUCTIVE_EXTERNAL)
    def job_write(job_id: str, data: str) -> JsonObject:
        """Write input to a running interactive PTY job."""
        return manager.job_write(job_id, data)

    @mcp.tool(title="Job resize", annotations=WRITE_LOCAL)
    def job_resize(job_id: str, cols: int, rows: int) -> JsonObject:
        """Resize a running interactive PTY job."""
        return manager.job_resize(job_id, cols, rows)

    @mcp.tool(title="Job wait", annotations=READ_ONLY_LOCAL)
    async def job_wait(job_id: str, timeout_seconds: float = 30) -> JsonObject:
        """Wait up to timeout_seconds for a job, then return current state."""
        return await manager.job_wait(job_id, timeout_seconds=timeout_seconds)

    @mcp.tool(title="Job cancel", annotations=DESTRUCTIVE_LOCAL)
    async def job_cancel(job_id: str, grace_seconds: float = 3) -> JsonObject:
        """Terminate a running job process group."""
        return await manager.job_cancel(job_id, grace_seconds=grace_seconds)
