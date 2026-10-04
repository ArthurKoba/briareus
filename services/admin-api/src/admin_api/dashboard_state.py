from __future__ import annotations

import asyncio

from admin_api.application.services import (
    AccountService,
    InvocationAuditService,
    OAuthSessionService,
    SnapshotService,
)
from admin_api.domain.accounts import Provider
from admin_api.infrastructure.snapshot_worker import (
    REVERSE_OVERVIEW_KEY,
    WORKSPACE_STATS_KEY,
    snapshot_meta,
)
from common.models import JsonObject, json_object


async def build_dashboard_state(
    accounts_service: AccountService,
    audit: InvocationAuditService,
    oauth_sessions: OAuthSessionService,
    snapshots: SnapshotService,
) -> JsonObject:
    accounts, calls, oauth, workspace, reverse_snapshot = await asyncio.gather(
        asyncio.to_thread(accounts_service.list),
        asyncio.to_thread(audit.summary),
        asyncio.to_thread(oauth_sessions.recent, limit=1000),
        asyncio.to_thread(snapshots.get, WORKSPACE_STATS_KEY),
        asyncio.to_thread(snapshots.get, REVERSE_OVERVIEW_KEY),
    )
    reverse_payload = reverse_snapshot.payload if reverse_snapshot is not None else {}
    projects = reverse_payload.get("projects")
    workers = reverse_payload.get("workers")
    project_items = projects if isinstance(projects, list) else []
    worker_items = workers if isinstance(workers, list) else []
    return {
        "accounts": {
            "total": len(accounts),
            "enabled": sum(1 for item in accounts if item.enabled),
            "by_provider": {
                provider.value: sum(
                    1 for item in accounts if item.provider == provider.value and item.enabled
                )
                for provider in Provider
            },
        },
        "calls": json_object(calls, context="dashboard calls"),
        "oauth": {
            "tracked": len(oauth),
            "active": sum(1 for item in oauth if item.status == "active"),
        },
        "workspace": workspace.payload if workspace is not None else {},
        "workspace_meta": snapshot_meta(workspace),
        "analysis": {
            "projects": len(project_items),
            "active_sessions": sum(
                1
                for item in project_items
                if isinstance(item, dict) and item.get("session") == "active"
            ),
            "workers": len(worker_items),
            "running_workers": sum(
                1 for item in worker_items if isinstance(item, dict) and bool(item.get("running"))
            ),
        },
        "analysis_meta": snapshot_meta(reverse_snapshot),
    }
