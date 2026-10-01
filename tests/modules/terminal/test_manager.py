from __future__ import annotations

from pathlib import Path

import pytest

from common.settings import TerminalSettings
from modules.terminal.manager import TerminalError, TerminalManager


@pytest.fixture
def manager(tmp_path: Path) -> TerminalManager:
    settings = TerminalSettings(
        workspace_root=tmp_path / "workspace",
        home=tmp_path / "home",
        shell="/bin/bash",
        max_exec_output_bytes=1024 * 1024,
        max_job_read_bytes=1024 * 1024,
        max_job_log_bytes=4 * 1024 * 1024,
    )
    return TerminalManager(settings)


@pytest.mark.asyncio
async def test_workspace_exec_and_path_confinement(manager: TerminalManager) -> None:
    manager.workspace_create("demo")
    result = await manager.terminal_exec("demo", "printf 'hello'")

    assert result["exit_code"] == 0
    assert result["stdout"] == "hello"

    with pytest.raises(TerminalError, match="escapes"):
        manager.resolve_cwd("demo", "../")


@pytest.mark.asyncio
async def test_job_read_is_cursor_incremental(manager: TerminalManager) -> None:
    manager.workspace_create("demo")
    started = await manager.job_start(
        "demo",
        "printf 'alpha-beta-gamma'",
        label="build",
    )
    job_id = str(started["job_id"])
    await manager.job_wait(job_id, timeout_seconds=2)

    first = await manager.job_read(job_id, cursor=0, max_bytes=5)
    second = await manager.job_read(
        job_id,
        cursor=int(first["next_cursor"]),
        max_bytes=1024,
    )

    assert first["output"] == "alpha"
    assert first["next_cursor"] == 5
    assert second["output"] == "-beta-gamma"
    assert second["eof"] is True


@pytest.mark.asyncio
async def test_interactive_job_uses_same_cursor_log(manager: TerminalManager) -> None:
    manager.workspace_create("demo")
    started = await manager.job_start(
        "demo",
        "cat",
        interactive=True,
        label="shell",
    )
    job_id = str(started["job_id"])
    manager.job_write(job_id, "uart-line\n")

    output = await manager.job_read(job_id, cursor=0, wait_seconds=1)
    assert "uart-line" in output["output"]

    await manager.job_cancel(job_id, grace_seconds=1)
    status = manager.job_status(job_id)
    assert status["state"] in {"cancelled", "failed"}


@pytest.mark.asyncio
async def test_workspace_delete_refuses_running_job(manager: TerminalManager) -> None:
    manager.workspace_create("demo")
    started = await manager.job_start("demo", "sleep 30")
    job_id = str(started["job_id"])

    with pytest.raises(TerminalError, match="active jobs"):
        await manager.workspace_delete("demo")

    await manager.job_cancel(job_id, grace_seconds=1)
    deleted = await manager.workspace_delete("demo")
    assert deleted["deleted"] is True


def test_persisted_running_job_becomes_interrupted(tmp_path: Path) -> None:
    settings = TerminalSettings(
        workspace_root=tmp_path / "workspace",
        home=tmp_path / "home",
        shell="/bin/bash",
    )
    first = TerminalManager(settings)
    first.workspace_create("demo")
    job_dir = first.jobs_root / "persisted"
    job_dir.mkdir(parents=True)
    (job_dir / "output.log").write_text("partial", encoding="utf-8")
    (job_dir / "metadata.json").write_text(
        """{
  "job_id": "persisted",
  "workspace_id": "demo",
  "command": "make",
  "cwd": "/tmp",
  "interactive": false,
  "label": "build",
  "state": "running",
  "created_at": 1,
  "started_at": 1,
  "ended_at": null,
  "exit_code": null,
  "signal_number": null,
  "pid": 123,
  "log_path": ""
}""",
        encoding="utf-8",
    )

    second = TerminalManager(settings)
    assert second.job_status("persisted")["state"] == "interrupted"


@pytest.mark.asyncio
async def test_terminal_exec_bounds_captured_output(manager: TerminalManager) -> None:
    manager.workspace_create("demo")
    result = await manager.terminal_exec(
        "demo",
        "printf '%010000d' 0",
        max_output_bytes=128,
    )

    assert result["exit_code"] == 0
    assert result["stdout_truncated"] is True
    assert len(str(result["stdout"]).encode()) <= 128


@pytest.mark.asyncio
async def test_completed_jobs_can_be_cleaned_up(manager: TerminalManager) -> None:
    manager.workspace_create("demo")
    started = await manager.job_start("demo", "printf done")
    job_id = str(started["job_id"])
    await manager.job_wait(job_id, timeout_seconds=2)

    preview = manager.job_cleanup(older_than_hours=1, dry_run=True)
    assert preview["count"] == 0

    manager._get_job(job_id).ended_at = 1
    removed = manager.job_cleanup(older_than_hours=1, dry_run=False)
    assert job_id in removed["job_ids"]
    with pytest.raises(TerminalError, match="job not found"):
        manager.job_status(job_id)


@pytest.mark.asyncio
async def test_workspace_delete_emits_cleanup_audit_log(
    manager: TerminalManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager.workspace_create("demo")
    path = manager.workspace_path("demo")
    (path / "artifact.bin").write_bytes(b"x" * 32)

    with caplog.at_level("INFO", logger="modules.terminal.manager"):
        result = await manager.workspace_delete("demo")

    assert result["freed_bytes"] == 32
    assert result["reason"] == "manual_delete"
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "workspace cleanup decision workspace_id=demo" in messages
    assert "reason=manual_delete" in messages
    assert "workspace cleanup completed workspace_id=demo" in messages
    assert "freed_bytes=32" in messages


@pytest.mark.asyncio
async def test_workspace_delete_logs_active_job_skip(
    manager: TerminalManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager.workspace_create("demo")
    started = await manager.job_start("demo", "sleep 30")
    job_id = str(started["job_id"])

    with (
        caplog.at_level("INFO", logger="modules.terminal.manager"),
        pytest.raises(TerminalError, match="active jobs"),
    ):
        await manager.workspace_delete("demo")

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "workspace cleanup skipped workspace_id=demo reason=active_jobs" in messages
    await manager.job_cancel(job_id, grace_seconds=1)


@pytest.mark.asyncio
async def test_job_cleanup_emits_retention_reason_and_freed_bytes(
    manager: TerminalManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager.workspace_create("demo")
    started = await manager.job_start("demo", "printf cleanup-data")
    job_id = str(started["job_id"])
    await manager.job_wait(job_id, timeout_seconds=2)
    manager._get_job(job_id).ended_at = 1

    with caplog.at_level("INFO", logger="modules.terminal.manager"):
        result = manager.job_cleanup(older_than_hours=1, dry_run=False)

    assert result["reason"] == "retention_expired"
    assert result["freed_bytes"] > 0
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "job cleanup scan started" in messages
    assert f"job cleanup candidate job_id={job_id}" in messages
    assert "reason=retention_expired" in messages
    assert f"job cleanup deleted job_id={job_id}" in messages
    assert "job cleanup scan completed" in messages
