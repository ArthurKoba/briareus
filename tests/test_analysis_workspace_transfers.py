from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from common.settings import AnalysisSettings
from modules.analysis.workspace_transfer import AnalysisTransferError, AnalysisWorkspaceTransfers
from modules.files.workspace_store import WorkspaceFileStore


class AnalysisWorkspaceTransferTests(unittest.TestCase):
    def make_transfers(self, root: Path) -> AnalysisWorkspaceTransfers:
        return AnalysisWorkspaceTransfers(
            AnalysisSettings(),
            WorkspaceFileStore(root),
            max_file_bytes=1024 * 1024,
        )

    def test_direct_upload_is_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transfers = self.make_transfers(Path(tmp))
            transfers._direct_upload_workspace_file = AsyncMock(
                return_value={
                    "path": "/artifacts/direct.bin",
                    "workspace_path": "firmware.bin",
                    "size_bytes": 1,
                    "sha256": "aa",
                    "transfer_method": "direct_raw",
                }
            )
            transfers._stage_workspace_file = AsyncMock()

            result = asyncio.run(
                transfers._transfer_workspace_file("project-1", "firmware.bin")
            )

            self.assertEqual(result["transfer_method"], "direct_raw")
            transfers._stage_workspace_file.assert_not_awaited()

    def test_staging_is_fallback_when_direct_upload_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transfers = self.make_transfers(Path(tmp))
            transfers._direct_upload_workspace_file = AsyncMock(
                side_effect=AnalysisTransferError("direct unavailable")
            )
            transfers._stage_workspace_file = AsyncMock(
                return_value={
                    "stage_id": "stage-1",
                    "path": "/artifacts/staged.bin",
                    "workspace_path": "firmware.bin",
                    "size_bytes": 1,
                    "sha256": "aa",
                    "transfer_method": "mcp_base64",
                }
            )

            result = asyncio.run(
                transfers._transfer_workspace_file("project-1", "firmware.bin")
            )

            self.assertEqual(result["transfer_method"], "mcp_base64")
            self.assertEqual(result["direct_upload_error"], "direct unavailable")
            transfers._stage_workspace_file.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
