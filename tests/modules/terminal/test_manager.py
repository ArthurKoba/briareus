from __future__ import annotations

from pathlib import Path

import pytest

from common.settings import FileSettings, TerminalSettings
from modules.files.file_store import FileStore
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


def test_workspace_files_round_trip(tmp_path: Path) -> None:
    store = FileStore(
        FileSettings(
            root=tmp_path / "files",
            upload_max_bytes=1024 * 1024,
        )
    )
    source = store.put_text("input.txt", "payload")
    manager = TerminalManager(
        TerminalSettings(
            workspace_root=tmp_path / "workspace",
            home=tmp_path / "home",
            shell="/bin/bash",
        ),
        store,
    )
    manager.workspace_create("demo")

    imported = manager.workspace_import_file(
        "demo",
        str(source["file_id"]),
        "src/input.txt",
    )
    assert Path(str(imported["path"])).read_text(encoding="utf-8") == "payload"

    exported = manager.workspace_export_file("demo", "src/input.txt", name="copy.txt")
    assert str(exported["file_id"]).startswith("sha256:")
    assert store.read(str(exported["file_id"]))["data_base64"]
