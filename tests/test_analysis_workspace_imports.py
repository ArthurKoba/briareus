from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from common.settings import AnalysisSettings
from modules.analysis.provider import AnalysisToolProvider
from modules.analysis.workspace_transfer import AnalysisTransferError, AnalysisWorkspaceTransfers
from modules.files.workspace_store import WorkspaceFileStore


class _BackendTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name
        self.title = None
        self.input_schema = {"type": "object", "properties": {}}


class AnalysisWorkspaceImportTests(unittest.TestCase):
    def test_raw_backend_import_tools_are_not_published(self) -> None:
        provider = AnalysisToolProvider(AnalysisSettings())
        tools = provider._adapt_catalog(
            [
                _BackendTool("import_file"),
                _BackendTool("import_program"),
                _BackendTool("restore_project"),
                _BackendTool("list_projects"),
            ]
        )
        self.assertEqual([tool.name for tool in tools], ["list_projects"])

    def test_import_uses_existing_workspace_path_without_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "firmware" / "image.bin"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"firmware-bytes")
            transfers = AnalysisWorkspaceTransfers(
                AnalysisSettings(),
                WorkspaceFileStore(root),
                max_file_bytes=1024 * 1024,
            )
            transfers._call = AsyncMock(return_value={"success": True})

            result = asyncio.run(
                transfers.import_workspace_file(
                    "project-1",
                    "firmware/image.bin",
                    project_folder="/official",
                    auto_analyze=False,
                )
            )

            transfers._call.assert_awaited_once_with(
                "import_file",
                {
                    "project_id": "project-1",
                    "file_path": source.as_posix(),
                    "project_folder": "/official",
                    "language": "",
                    "compiler_spec": "",
                    "auto_analyze": False,
                },
            )
            self.assertEqual(result["size_bytes"], len(b"firmware-bytes"))
            self.assertNotIn("stage_id", repr(result))
            self.assertNotIn("data_base64", repr(transfers._call.await_args))

    def test_import_rejects_missing_workspace_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transfers = AnalysisWorkspaceTransfers(
                AnalysisSettings(),
                WorkspaceFileStore(Path(tmp)),
                max_file_bytes=1024 * 1024,
            )
            with self.assertRaisesRegex(AnalysisTransferError, "Files/Terminal"):
                asyncio.run(
                    transfers.import_workspace_file(
                        "project-1",
                        "missing.bin",
                        auto_analyze=False,
                    )
                )


if __name__ == "__main__":
    unittest.main()
