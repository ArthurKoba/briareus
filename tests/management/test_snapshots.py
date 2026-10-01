from __future__ import annotations

from pathlib import Path

import pytest

from common.models import JsonObject
from management.application.services import SnapshotService
from management.infrastructure.database import Base, create_database
from management.infrastructure.repositories import SqlAlchemySnapshotRepository
from management.infrastructure.snapshot_worker import (
    REVERSE_OVERVIEW_KEY,
    WORKSPACE_STATS_KEY,
    SnapshotRefresher,
    coverage_snapshot_key,
)


def _service(tmp_path: Path) -> tuple[SnapshotService, object]:
    engine, sessions = create_database(f"sqlite:///{tmp_path / 'snapshots.sqlite3'}")
    Base.metadata.create_all(engine)
    return SnapshotService(SqlAlchemySnapshotRepository(sessions)), engine


def test_snapshot_cache_preserves_last_success_and_refresh_metadata(tmp_path: Path) -> None:
    snapshots, engine = _service(tmp_path)
    created = snapshots.ensure(
        WORKSPACE_STATS_KEY,
        category="workspace_stats",
        parameters={},
        refresh_after_seconds=300,
    )
    assert created.status == "pending"
    assert snapshots.due("workspace_stats")

    snapshots.mark_attempt(WORKSPACE_STATS_KEY)
    refreshing = snapshots.get(WORKSPACE_STATS_KEY)
    assert refreshing is not None
    assert refreshing.status == "refreshing"
    assert snapshots.due("workspace_stats") == []

    ready = snapshots.store_success(
        WORKSPACE_STATS_KEY,
        {"files": 123, "size_bytes": 456},
    )
    assert ready.status == "ready"
    assert ready.payload["files"] == 123
    assert ready.updated_at is not None
    assert snapshots.due("workspace_stats") == []
    engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_background_refresher_populates_workspace_and_reverse_snapshots(
    tmp_path: Path,
) -> None:
    snapshots, engine = _service(tmp_path)

    class FakeFiles:
        def stats(self) -> JsonObject:
            return {"files": 12, "size_bytes": 34, "size_display": "34 B"}

    class FakeReverse:
        async def overview(self) -> JsonObject:
            return {"projects": [{"project_id": "p1"}], "workers": []}

    refresher = SnapshotRefresher(
        snapshots,
        FakeFiles(),  # type: ignore[arg-type]
        FakeReverse(),  # type: ignore[arg-type]
    )
    await refresher.ensure_base_snapshots()
    await refresher._refresh_workspace_once()
    await refresher._refresh_reverse_once()

    workspace = snapshots.get(WORKSPACE_STATS_KEY)
    reverse = snapshots.get(REVERSE_OVERVIEW_KEY)
    assert workspace is not None and workspace.payload["files"] == 12
    assert reverse is not None and reverse.payload["projects"] == [{"project_id": "p1"}]
    engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_coverage_subscription_runs_in_background_and_is_cached(tmp_path: Path) -> None:
    snapshots, engine = _service(tmp_path)
    key = coverage_snapshot_key("project-1", "program.bin", full=True)
    snapshots.ensure(
        key,
        category="reverse_coverage",
        parameters={"project_id": "project-1", "program": "program.bin", "full": True},
        refresh_after_seconds=1800,
    )

    class FakeFiles:
        def stats(self) -> JsonObject:
            return {}

    class FakeReverse:
        async def coverage(self, project_id: str, program: str, *, full: bool) -> JsonObject:
            assert project_id == "project-1"
            assert program == "program.bin"
            assert full is True
            return {
                "project_id": project_id,
                "program": program,
                "approximate": False,
                "evaluated_functions": 10,
            }

    refresher = SnapshotRefresher(
        snapshots,
        FakeFiles(),  # type: ignore[arg-type]
        FakeReverse(),  # type: ignore[arg-type]
    )
    await refresher._refresh_coverage_once()

    cached = snapshots.get(key)
    assert cached is not None
    assert cached.status == "ready"
    assert cached.payload["evaluated_functions"] == 10
    engine.dispose()  # type: ignore[attr-defined]
