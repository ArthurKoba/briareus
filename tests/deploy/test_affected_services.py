from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path("deploy/coolify/affected-services.sh")


def _resolve(*paths: str) -> list[str]:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--resolve-paths"],
        input="\n".join(paths) + "\n",
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def test_analysis_change_only_restarts_analysis() -> None:
    assert _resolve("src/modules/analysis/provider.py") == ["analysis"]


def test_files_change_restarts_all_files_consumers() -> None:
    assert _resolve("src/modules/files/store_core.py") == [
        "management",
        "files",
        "curl",
    ]


def test_bridge_and_auth_changes_are_independent() -> None:
    assert _resolve(
        "src/bridge/server.py",
        "src/auth_service/provider.py",
    ) == ["auth", "gateway"]


def test_common_change_restarts_every_runtime() -> None:
    assert _resolve("src/common/settings.py") == [
        "auth",
        "gateway",
        "management",
        "github",
        "gitlab",
        "files",
        "curl",
        "analysis",
        "ghidra",
    ]


def test_non_runtime_change_restarts_nothing() -> None:
    assert _resolve("docs/architecture/overview.md", "tests/bridge/test_server.py") == []
