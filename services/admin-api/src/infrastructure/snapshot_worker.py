from __future__ import annotations

import asyncio
import logging
from typing import cast

from application.services import SnapshotService

from common.models import JsonObject
from infrastructure.files import FileAdminStore
from infrastructure.reverse import ReverseAdminClient

logger = logging.getLogger(__name__)

WORKSPACE_STATS_KEY = "workspace:stats"
REVERSE_OVERVIEW_KEY = "reverse:overview"
WORKSPACE_STATS_REFRESH_SECONDS = 5 * 60
REVERSE_OVERVIEW_REFRESH_SECONDS = 30
QUICK_COVERAGE_REFRESH_SECONDS = 10 * 60
FULL_COVERAGE_REFRESH_SECONDS = 30 * 60


class SnapshotRefresher:
    def __init__(
        self,
        snapshots: SnapshotService,
        files: FileAdminStore,
        reverse: ReverseAdminClient,
    ) -> None:
        self.snapshots = snapshots
        self.files = files
        self.reverse = reverse
        self._coverage_wakeup = asyncio.Event()

    async def ensure_base_snapshots(self) -> None:
        await self.snapshots.ensure(
            WORKSPACE_STATS_KEY,
            category="workspace_stats",
            parameters={},
            refresh_after_seconds=WORKSPACE_STATS_REFRESH_SECONDS,
        )
        await self.snapshots.ensure(
            REVERSE_OVERVIEW_KEY,
            category="reverse_overview",
            parameters={},
            refresh_after_seconds=REVERSE_OVERVIEW_REFRESH_SECONDS,
        )

    async def _refresh_workspace_once(self) -> None:
        due = await self.snapshots.due("workspace_stats", limit=1)
        if not due:
            return
        snapshot = due[0]
        await self.snapshots.mark_attempt(snapshot.key)
        try:
            payload = await asyncio.to_thread(self.files.stats)
            await self.snapshots.store_success(
                snapshot.key,
                cast(dict[str, object], payload),
            )
        except Exception as exc:
            logger.exception("workspace snapshot refresh failed")
            await self.snapshots.store_error(snapshot.key, exc)

    async def _refresh_reverse_once(self) -> None:
        due = await self.snapshots.due("reverse_overview", limit=1)
        if not due:
            return
        snapshot = due[0]
        await self.snapshots.mark_attempt(snapshot.key)
        try:
            payload = await self.reverse.overview()
            await self.snapshots.store_success(
                snapshot.key,
                cast(dict[str, object], payload),
            )
        except Exception as exc:
            logger.exception("reverse overview snapshot refresh failed")
            await self.snapshots.store_error(snapshot.key, exc)

    async def _refresh_coverage_once(self) -> bool:
        due = await self.snapshots.due(
            "reverse_coverage",
            retry_after_seconds=60,
            limit=100,
        )
        if not due:
            return False
        snapshot = due[0]
        project_id = snapshot.parameters.get("project_id")
        program = snapshot.parameters.get("program")
        full = snapshot.parameters.get("full")
        if not isinstance(project_id, str) or not project_id:
            exc = ValueError("cached coverage project_id is missing")
            await self.snapshots.store_error(snapshot.key, exc)
            return True
        if not isinstance(program, str) or not program:
            exc = ValueError("cached coverage program is missing")
            await self.snapshots.store_error(snapshot.key, exc)
            return True
        full_mode = bool(full)
        await self.snapshots.mark_attempt(snapshot.key)
        try:
            payload = await self.reverse.coverage(project_id, program, full=full_mode)
            await self.snapshots.store_success(
                snapshot.key,
                cast(dict[str, object], payload),
            )
        except Exception as exc:
            logger.exception(
                "reverse coverage snapshot refresh failed project=%s program=%s full=%s",
                project_id,
                program,
                full_mode,
            )
            await self.snapshots.store_error(snapshot.key, exc)
        return True

    def notify_coverage_requested(self) -> None:
        self._coverage_wakeup.set()

    async def workspace_loop(self) -> None:
        while True:
            await self._refresh_workspace_once()
            await asyncio.sleep(60)

    async def reverse_loop(self) -> None:
        while True:
            await self._refresh_reverse_once()
            await asyncio.sleep(REVERSE_OVERVIEW_REFRESH_SECONDS)

    async def coverage_loop(self) -> None:
        while True:
            while await self._refresh_coverage_once():
                pass
            try:
                await asyncio.wait_for(self._coverage_wakeup.wait(), timeout=60)
            except TimeoutError:
                pass
            finally:
                self._coverage_wakeup.clear()


def coverage_snapshot_key(project_id: str, program: str, *, full: bool) -> str:
    import hashlib

    mode = "full" if full else "quick"
    digest = hashlib.sha256(f"{project_id}\0{program}\0{mode}".encode()).hexdigest()[:24]
    return f"reverse:coverage:{mode}:{digest}"


def coverage_refresh_seconds(*, full: bool) -> int:
    return FULL_COVERAGE_REFRESH_SECONDS if full else QUICK_COVERAGE_REFRESH_SECONDS


def snapshot_meta(snapshot: object) -> JsonObject:
    from domain.snapshots import CachedSnapshot

    if not isinstance(snapshot, CachedSnapshot):
        return {}
    age = snapshot.age_seconds()
    return {
        "status": snapshot.status,
        "updated_at": snapshot.updated_at.isoformat() if snapshot.updated_at else None,
        "attempted_at": snapshot.attempted_at.isoformat() if snapshot.attempted_at else None,
        "age_seconds": round(age, 1) if age is not None else None,
        "stale": snapshot.stale(),
        "error_type": snapshot.error_type,
        "error_message": snapshot.error_message,
    }
