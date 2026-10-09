# ruff: noqa: B008  # FastAPI dependencies
"""Project-scoped operational read projections for disabled C1-B2 draft BFF.

No OS process liveness, Browser screen, Ghidra native secret, filesystem path,
terminal output, storage root, credential or provider endpoint is exposed.
The read contract is a database snapshot, not authoritative runtime health.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._platform_application import PlatformApplication
from authorization._platform_permissions import project_permit
from authorization._project_access import CallerPrincipal
from common.platform_ids import PlatformProjectId
from projects._file_quota_persistence import FileObjectRow, FileQuotaAccountRow
from projects._native_import_persistence import NativeImportRow, NativeProjectRow
from projects._runtime_persistence import RuntimeJobRow, RuntimeSessionRow

Caller = Callable[..., Awaitable[CallerPrincipal]]


class OperationalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeState(OperationalModel):
    runtime_session_uuid: UUID
    actor_user_id: UUID
    agent_session_uuid: UUID
    kind: str
    status: str
    cleanup_state: str
    version: int = Field(ge=1)
    idle_expires_at: datetime
    hard_expires_at: datetime
    lease_expires_at: datetime


class RuntimeJobState(OperationalModel):
    job_uuid: UUID
    runtime_session_uuid: UUID
    operation: str
    status: str
    version: int = Field(ge=1)
    hard_expires_at: datetime


class FileQuotaState(OperationalModel):
    byte_limit: int = Field(ge=0)
    used_bytes: int = Field(ge=0)
    reserved_bytes: int = Field(ge=0)
    frozen: bool
    version: int = Field(ge=1)
    file_count: int = Field(ge=0)


class NativeProjectState(OperationalModel):
    native_project_id: UUID
    enabled: bool
    version: int = Field(ge=1)


class NativeImportState(OperationalModel):
    import_uuid: UUID
    operation_uuid: UUID
    native_project_id: UUID
    source_file_version: int = Field(ge=1)
    status: str
    version: int = Field(ge=1)
    cleanup_state: str


class ProjectOperationalState(OperationalModel):
    project_id: UUID
    project_access_revision: str
    observed_at: datetime
    limit: int = Field(ge=1, le=100)
    runtime_sessions: list[RuntimeState]
    jobs: list[RuntimeJobState]
    quota: FileQuotaState | None
    native_projects: list[NativeProjectState]
    native_imports: list[NativeImportState]
    note: str = (
        "Database metadata only. Runtime process, Files storage and native "
        "Ghidra state require independently confirmed service observations."
    )


async def _quota(tx: AsyncSession, project_id: UUID) -> FileQuotaState | None:
    row = await tx.scalar(
        select(FileQuotaAccountRow).where(FileQuotaAccountRow.project_id == project_id)
    )
    if row is None:
        return None
    count = await tx.scalar(
        select(func.count(FileObjectRow.id)).where(
            FileObjectRow.project_id == project_id,
            FileObjectRow.deleted.is_(False),
        )
    )
    return FileQuotaState(
        byte_limit=row.byte_limit,
        used_bytes=row.used_bytes,
        reserved_bytes=row.reserved_bytes,
        frozen=row.frozen,
        version=row.version,
        file_count=count or 0,
    )


def build_unmounted_state_router(
    application: PlatformApplication,
    caller: Caller,
) -> APIRouter:
    router = APIRouter(tags=["platform-operations-draft"])

    @router.get("/projects/{project_id}/operational-state", response_model=ProjectOperationalState)
    async def operational_state(
        project_id: UUID,
        limit: int = Query(default=50, ge=1, le=100),
        subject: CallerPrincipal = Depends(caller),
    ) -> ProjectOperationalState:
        async with application.db.transaction() as tx:
            permit = await project_permit(tx, application, subject, PlatformProjectId(project_id))
            runtimes = list(
                await tx.scalars(
                    select(RuntimeSessionRow)
                    .where(RuntimeSessionRow.project_id == project_id)
                    .order_by(
                        RuntimeSessionRow.created_at.desc(),
                        RuntimeSessionRow.runtime_session_uuid,
                    )
                    .limit(limit)
                )
            )
            jobs = list(
                await tx.scalars(
                    select(RuntimeJobRow)
                    .where(RuntimeJobRow.project_id == project_id)
                    .order_by(RuntimeJobRow.created_at.desc(), RuntimeJobRow.job_uuid)
                    .limit(limit)
                )
            )
            native = list(
                await tx.scalars(
                    select(NativeProjectRow)
                    .where(NativeProjectRow.project_id == project_id)
                    .order_by(NativeProjectRow.created_at.desc(), NativeProjectRow.id)
                    .limit(limit)
                )
            )
            imports = list(
                await tx.scalars(
                    select(NativeImportRow)
                    .where(NativeImportRow.project_id == project_id)
                    .order_by(NativeImportRow.created_at.desc(), NativeImportRow.import_uuid)
                    .limit(limit)
                )
            )
            quota = await _quota(tx, project_id)
            return ProjectOperationalState(
                project_id=project_id,
                project_access_revision=permit.decision_version,
                observed_at=datetime.now(UTC),
                limit=limit,
                runtime_sessions=[
                    RuntimeState(
                        runtime_session_uuid=row.runtime_session_uuid,
                        actor_user_id=row.actor_user_id,
                        agent_session_uuid=row.agent_session_uuid,
                        kind=row.kind,
                        status=row.status,
                        cleanup_state=row.cleanup_state,
                        version=row.version,
                        idle_expires_at=row.idle_expires_at,
                        hard_expires_at=row.hard_expires_at,
                        lease_expires_at=row.lease_expires_at,
                    )
                    for row in runtimes
                ],
                jobs=[
                    RuntimeJobState(
                        job_uuid=row.job_uuid,
                        runtime_session_uuid=row.runtime_session_uuid,
                        operation=row.operation,
                        status=row.status,
                        version=row.version,
                        hard_expires_at=row.hard_expires_at,
                    )
                    for row in jobs
                ],
                quota=quota,
                native_projects=[
                    NativeProjectState(
                        native_project_id=row.id,
                        enabled=row.enabled,
                        version=row.version,
                    )
                    for row in native
                ],
                native_imports=[
                    NativeImportState(
                        import_uuid=row.import_uuid,
                        operation_uuid=row.operation_uuid,
                        native_project_id=row.native_project_id,
                        source_file_version=row.source_file_version,
                        status=row.status,
                        version=row.version,
                        cleanup_state=row.cleanup_state,
                    )
                    for row in imports
                ],
            )

    return router
