from __future__ import annotations

import base64
from pathlib import Path

import pytest

from common.settings import AnalysisSettings
from modules.analysis.workspace_transfer import AnalysisWorkspaceTransfers
from modules.files.workspace_store import WorkspaceFileStore


@pytest.fixture
def transfers(tmp_path: Path) -> AnalysisWorkspaceTransfers:
    workspace = WorkspaceFileStore(tmp_path / "workspace")
    return AnalysisWorkspaceTransfers(
        AnalysisSettings(backend_url="http://ghidra:8000/mcp"),
        workspace,
        max_file_bytes=16 * 1024 * 1024,
        chunk_bytes=4,
    )


@pytest.mark.asyncio
async def test_import_workspace_file_stages_imports_and_cleans_up(
    transfers: AnalysisWorkspaceTransfers,
    monkeypatch,
) -> None:
    transfers.workspace.write_text("firmware/input.bin", "abcdefgh")
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_call(name: str, arguments: dict[str, object]):
        calls.append((name, arguments))
        if name == "artifact_stage_begin":
            return {"stage_id": "stage-1"}
        if name == "artifact_stage_write":
            raw = base64.b64decode(str(arguments["data_base64"]))
            return {"next_offset": int(arguments["offset"]) + len(raw)}
        if name == "artifact_stage_finish":
            return {"path": "/artifacts/.koba-stage/stage-1/input.bin"}
        if name == "import_file":
            return {"imported": True}
        if name == "artifact_stage_cancel":
            return {"cancelled": True}
        raise AssertionError(name)

    monkeypatch.setattr(transfers, "_call", fake_call)

    result = await transfers.import_workspace_file(
        "project-1",
        "firmware/input.bin",
        auto_analyze=False,
    )

    assert result["result"] == {"imported": True}
    assert [name for name, _args in calls] == [
        "artifact_stage_begin",
        "artifact_stage_write",
        "artifact_stage_write",
        "artifact_stage_finish",
        "import_file",
        "artifact_stage_cancel",
    ]
    assert calls[0][1]["size_bytes"] == 8
    assert calls[4][1]["file_path"] == "/artifacts/.koba-stage/stage-1/input.bin"


@pytest.mark.asyncio
async def test_copy_artifact_reads_chunks_into_workspace(
    transfers: AnalysisWorkspaceTransfers,
    monkeypatch,
) -> None:
    payload = b"abcdefghij"

    async def fake_call(name: str, arguments: dict[str, object]):
        if name == "artifact_file_delete":
            return {"deleted": True}
        assert name == "artifact_file_read"
        offset = int(arguments["offset"])
        chunk = payload[offset : offset + 4]
        next_offset = offset + len(chunk)
        return {
            "data_base64": base64.b64encode(chunk).decode("ascii"),
            "next_offset": next_offset,
            "size_bytes": len(payload),
            "eof": next_offset >= len(payload),
        }

    monkeypatch.setattr(transfers, "_call", fake_call)

    result = await transfers._copy_artifact_to_workspace(
        "project-1",
        "/artifacts/exports/demo.gzf",
        "exports/demo.gzf",
        overwrite=False,
    )

    assert result["path"] == "exports/demo.gzf"
    assert transfers.workspace.path_for("exports/demo.gzf").read_bytes() == payload
    assert result["source_artifact_path"] == "/artifacts/exports/demo.gzf"
    assert result["source_deleted"] is True


@pytest.mark.asyncio
async def test_export_program_copies_returned_artifact(
    transfers: AnalysisWorkspaceTransfers,
    monkeypatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_call(name: str, arguments: dict[str, object]):
        calls.append((name, arguments))
        if name == "export_program":
            return {"path": "/artifacts/exports/program.gzf"}
        if name == "artifact_file_read":
            return {
                "data_base64": base64.b64encode(b"gzf").decode("ascii"),
                "next_offset": 3,
                "size_bytes": 3,
                "eof": True,
            }
        if name == "artifact_file_delete":
            return {"deleted": True}
        raise AssertionError(name)

    monkeypatch.setattr(transfers, "_call", fake_call)

    result = await transfers.export_program_to_workspace(
        "project-1",
        "program",
        "exports/program.gzf",
    )

    assert result["path"] == "exports/program.gzf"
    assert transfers.workspace.path_for("exports/program.gzf").read_bytes() == b"gzf"
    assert calls[0][0] == "export_program"
    assert calls[0][1]["output_dir"] == "/artifacts/exports"


@pytest.mark.asyncio
async def test_import_workspace_program_uses_staged_gzf(
    transfers: AnalysisWorkspaceTransfers,
    monkeypatch,
) -> None:
    transfers.workspace.write_text("exports/input.gzf", "package")
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_call(name: str, arguments: dict[str, object]):
        calls.append((name, arguments))
        if name == "artifact_stage_begin":
            return {"stage_id": "stage-2"}
        if name == "artifact_stage_write":
            raw = base64.b64decode(str(arguments["data_base64"]))
            return {"next_offset": int(arguments["offset"]) + len(raw)}
        if name == "artifact_stage_finish":
            return {"path": "/artifacts/.koba-stage/stage-2/input.gzf"}
        if name == "import_program":
            return {"imported": True}
        if name == "artifact_stage_cancel":
            return {"cancelled": True}
        raise AssertionError(name)

    monkeypatch.setattr(transfers, "_call", fake_call)

    result = await transfers.import_workspace_program(
        "project-1",
        "exports/input.gzf",
        target_folder="/imports",
    )

    import_call = next(args for name, args in calls if name == "import_program")
    assert import_call["gzf_path"] == "/artifacts/.koba-stage/stage-2/input.gzf"
    assert import_call["target_folder"] == "/imports"
    assert result["stage_cleanup_error"] == ""


@pytest.mark.asyncio
async def test_restore_workspace_project_uses_staged_gar(
    transfers: AnalysisWorkspaceTransfers,
    monkeypatch,
) -> None:
    transfers.workspace.write_text("exports/project.gar", "archive")
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_call(name: str, arguments: dict[str, object]):
        calls.append((name, arguments))
        if name == "artifact_stage_begin":
            return {"stage_id": "stage-3"}
        if name == "artifact_stage_write":
            raw = base64.b64decode(str(arguments["data_base64"]))
            return {"next_offset": int(arguments["offset"]) + len(raw)}
        if name == "artifact_stage_finish":
            return {"path": "/artifacts/.koba-stage/stage-3/project.gar"}
        if name == "restore_project":
            return {"restored": True}
        if name == "artifact_stage_cancel":
            return {"cancelled": True}
        raise AssertionError(name)

    monkeypatch.setattr(transfers, "_call", fake_call)

    await transfers.restore_workspace_project(
        "project-1",
        "exports/project.gar",
        "restored-project",
    )

    restore_call = next(args for name, args in calls if name == "restore_project")
    assert restore_call["gar_path"] == "/artifacts/.koba-stage/stage-3/project.gar"
    assert restore_call["project_name"] == "restored-project"


@pytest.mark.asyncio
async def test_failed_import_cleans_up_stage(
    transfers: AnalysisWorkspaceTransfers,
    monkeypatch,
) -> None:
    transfers.workspace.write_text("firmware/fail.bin", "payload")
    calls: list[str] = []

    async def fake_call(name: str, arguments: dict[str, object]):
        calls.append(name)
        if name == "artifact_stage_begin":
            return {"stage_id": "stage-fail"}
        if name == "artifact_stage_write":
            raw = base64.b64decode(str(arguments["data_base64"]))
            return {"next_offset": int(arguments["offset"]) + len(raw)}
        if name == "artifact_stage_finish":
            return {"path": "/artifacts/.koba-stage/stage-fail/fail.bin"}
        if name == "import_file":
            raise RuntimeError("import failed")
        if name == "artifact_stage_cancel":
            return {"cancelled": True}
        raise AssertionError(name)

    monkeypatch.setattr(transfers, "_call", fake_call)

    with pytest.raises(RuntimeError, match="import failed"):
        await transfers.import_workspace_file(
            "project-1",
            "firmware/fail.bin",
        )

    assert calls[-1] == "artifact_stage_cancel"
