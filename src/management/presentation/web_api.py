from __future__ import annotations

import asyncio
import hmac
import json
import posixpath
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import FileResponse, StreamingResponse

from common.models import JsonObject, JsonValue, json_object
from common.runtime_policy_contracts import (
    GitHubRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)
from common.settings import ManagementSettings
from management.application.services import (
    AccountService,
    InvocationAuditService,
    ManagementConfigService,
    OAuthSessionService,
    RuntimeSettingsService,
    SnapshotService,
)
from management.dashboard_state import build_dashboard_state
from management.domain.accounts import Account, AuthType, Provider
from management.domain.configuration import ManagementConfig
from management.infrastructure.files import FileAdminStore
from management.infrastructure.reverse import ReverseAdminClient
from management.infrastructure.snapshot_worker import (
    REVERSE_OVERVIEW_KEY,
    WORKSPACE_STATS_KEY,
    SnapshotRefresher,
    coverage_refresh_seconds,
    coverage_snapshot_key,
    snapshot_meta,
)
from management.infrastructure.terminal import TerminalAdminClient
from management.infrastructure.web import WebAdminClient
from management.realtime import RealtimeBus
from management.telemetry_ingest import FrontendTelemetryProxy

_SESSION_KEY = "management_admin"


@dataclass(frozen=True)
class WebApiServices:
    accounts: AccountService
    audit: InvocationAuditService
    oauth_sessions: OAuthSessionService
    snapshots: SnapshotService
    config: ManagementConfigService
    runtime_settings: RuntimeSettingsService
    files: FileAdminStore
    reverse: ReverseAdminClient
    terminal: TerminalAdminClient
    web: WebAdminClient
    snapshot_refresher: SnapshotRefresher
    realtime: RealtimeBus | None = None
    telemetry: FrontendTelemetryProxy | None = None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str


class AccountPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alias: str
    provider: Provider
    auth_type: AuthType
    base_url: str = ""
    external_id: str = ""
    verify_tls: bool = True
    ca_cert_pem: str = ""
    enabled: bool = True
    credential: str = ""


class ProjectCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    parent_dir: str = ""


class WorkerControlPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class WorkerRecoverPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout_seconds: float = Field(4.0, ge=1.0, le=30.0)


class ViewportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_id: str = Field(min_length=1, max_length=255)
    width: int = Field(ge=320, le=7680)
    height: int = Field(ge=240, le=4320)


class FrontendTelemetryBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[JsonValue] = Field(min_length=1, max_length=500)


class SettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logging_enabled: bool = True
    logging_capture_payloads: bool = True
    logging_retention_days: int = Field(30, ge=1, le=3650)
    logging_max_records: int = Field(10_000, ge=100, le=1_000_000)
    maintenance_interval_minutes: int = Field(60, ge=1, le=1440)
    terminal_max_exec_timeout_seconds: int = Field(21_600, ge=1, le=86_400)
    terminal_max_job_runtime_seconds: int = Field(43_200, ge=1, le=604_800)
    mcp_call_timeout_seconds: int = Field(5, ge=1, le=300)
    github_local_first_guidance: bool = True
    github_local_git_transport_enabled: bool = False
    github_remote_source_mutations_enabled: bool = True
    reverse_idle_timeout_seconds: float = Field(900.0, ge=0, le=86_400)


def _oauth_json(session: object) -> JsonObject:
    values = dict(getattr(session, "__dict__", {}))
    for field in (
        "created_at",
        "updated_at",
        "last_used_at",
        "last_refresh_at",
        "access_expires_at",
        "refresh_expires_at",
        "revoked_at",
    ):
        value = values.get(field)
        values[field] = value.isoformat() if value is not None else None
    return values


def _account_from_payload(payload: AccountPayload, *, existing: Account | None = None) -> Account:
    values: dict[str, object] = {
        "alias": payload.alias,
        "provider": payload.provider,
        "auth_type": payload.auth_type,
        "base_url": payload.base_url,
        "external_id": payload.external_id,
        "verify_tls": payload.verify_tls,
        "ca_cert_pem": payload.ca_cert_pem,
        "enabled": payload.enabled,
    }
    if existing is not None:
        values.update(
            id=existing.id,
            created_at=existing.created_at,
            updated_at=existing.updated_at,
        )
    return Account.model_validate(values)


def build_admin_api_router(
    settings: ManagementSettings, services: WebApiServices | None = None
) -> APIRouter:
    router = APIRouter(prefix="/admin/api", tags=["admin"])

    def authenticated_username(request: Request) -> str | None:
        username = request.session.get(_SESSION_KEY)
        if not isinstance(username, str) or not username:
            return None
        if not hmac.compare_digest(username, settings.admin_username):
            request.session.clear()
            return None
        return username

    def require_user(request: Request) -> str:
        username = authenticated_username(request)
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
        return username

    def same_origin(request: Request) -> None:
        origin = request.headers.get("origin", "")
        if not origin:
            return
        public_host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        if urlsplit(origin).netloc.casefold() != public_host.casefold():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="origin rejected")

    def available() -> WebApiServices:
        if services is None:
            raise HTTPException(status_code=503, detail="management API services unavailable")
        return services

    def mutation(request: Request) -> WebApiServices:
        require_user(request)
        same_origin(request)
        return available()

    async def publish_management_event(api: WebApiServices, event_type: str, data: object) -> None:
        if api.realtime is not None:
            await api.realtime.publish("management.events", event_type, data)

    @router.get("/session")
    def session_state(request: Request) -> JsonObject:
        username = authenticated_username(request)
        return {"authenticated": username is not None, "username": username}

    @router.post("/login")
    def login(payload: LoginRequest, request: Request) -> JsonObject:
        same_origin(request)
        valid_user = hmac.compare_digest(payload.username, settings.admin_username)
        valid_password = hmac.compare_digest(payload.password, settings.admin_password)
        if not (valid_user and valid_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
            )
        request.session[_SESSION_KEY] = settings.admin_username
        return {"authenticated": True, "username": settings.admin_username}

    @router.post("/logout")
    def logout(request: Request) -> JsonObject:
        same_origin(request)
        request.session.clear()
        return {"authenticated": False, "username": None}

    @router.get("/bootstrap")
    def bootstrap(request: Request) -> JsonObject:
        require_user(request)
        return {
            "product": "MCP Management",
            "environment": "runtime",
            "navigation": [
                {"id": "overview", "label": "Overview", "enabled": True},
                {"id": "accounts", "label": "Accounts", "enabled": True},
                {"id": "calls", "label": "MCP Calls", "enabled": True},
                {"id": "files", "label": "Files", "enabled": True},
                {"id": "terminal", "label": "Terminal", "enabled": True},
                {"id": "browser", "label": "Browser", "enabled": True},
                {"id": "analysis", "label": "Analysis", "enabled": True},
                {"id": "oauth", "label": "OAuth Sessions", "enabled": True},
                {"id": "settings", "label": "Settings", "enabled": True},
            ],
        }

    @router.get("/dashboard")
    async def dashboard(request: Request) -> JsonObject:
        require_user(request)
        api = available()
        return await build_dashboard_state(
            api.accounts, api.audit, api.oauth_sessions, api.snapshots
        )

    @router.get("/accounts")
    async def accounts(request: Request, provider: Provider | None = None) -> JsonObject:
        require_user(request)
        items = await asyncio.to_thread(available().accounts.list, provider=provider)
        return {"accounts": [item.model_dump(mode="json") for item in items], "count": len(items)}

    @router.post("/accounts", status_code=201)
    async def create_account(payload: AccountPayload, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            account = _account_from_payload(payload)
            saved = await asyncio.to_thread(
                api.accounts.create, account, credential=payload.credential
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response = saved.public()
        await publish_management_event(api, "account.created", response)
        return response

    @router.put("/accounts/{provider}/{account_id}")
    async def update_account(
        provider: Provider, account_id: str, payload: AccountPayload, request: Request
    ) -> JsonObject:
        api = mutation(request)
        if payload.provider is not provider:
            raise HTTPException(status_code=400, detail="provider cannot be changed")
        try:
            existing = await asyncio.to_thread(
                api.accounts.get, account_id, provider=provider, enabled_only=False
            )
            saved = await asyncio.to_thread(
                api.accounts.update, _account_from_payload(payload, existing=existing)
            )
            if payload.credential.strip():
                await asyncio.to_thread(
                    api.accounts.set_credential, saved.id, payload.credential, provider=provider
                )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response = saved.public()
        await publish_management_event(api, "account.updated", response)
        return response

    @router.delete("/accounts/{provider}/{account_id}")
    async def delete_account(provider: Provider, account_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            await asyncio.to_thread(api.accounts.delete, account_id, provider=provider)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        response: JsonObject = {"deleted": True, "id": account_id}
        await publish_management_event(api, "account.deleted", response)
        return response

    @router.post("/accounts/{provider}/{account_id}/verify")
    async def verify_account(provider: Provider, account_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await asyncio.to_thread(api.accounts.verify, account_id, provider=provider)
            await publish_management_event(api, "account.verified", result)
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/calls")
    async def calls(request: Request, limit: int = Query(100, ge=1, le=1000)) -> JsonObject:
        require_user(request)
        items = await asyncio.to_thread(available().audit.recent, limit=limit)
        return {"events": [item.model_dump(mode="json") for item in items], "count": len(items)}

    @router.delete("/calls")
    async def clear_calls(request: Request) -> JsonObject:
        api = mutation(request)
        removed = await asyncio.to_thread(api.audit.clear)
        response: JsonObject = {"deleted": removed}
        await publish_management_event(api, "calls.cleared", response)
        return response

    @router.delete("/calls/{call_id}")
    async def delete_call(call_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        removed = await asyncio.to_thread(api.audit.delete, call_id)
        if not removed:
            raise HTTPException(status_code=404, detail="call not found")
        response: JsonObject = {"deleted": True, "id": call_id}
        await publish_management_event(api, "calls.deleted", response)
        return response

    @router.get("/calls/stream")
    async def calls_stream(request: Request) -> StreamingResponse:
        require_user(request)
        audit = available().audit

        async def events() -> AsyncIterator[str]:
            seen: set[str] = set()
            initial = await asyncio.to_thread(audit.recent, limit=100)
            for item in reversed(initial):
                seen.add(item.id)
                yield f"data: {json.dumps(item.model_dump(mode='json'), ensure_ascii=False)}\\n\\n"
            while not await request.is_disconnected():
                latest = await asyncio.to_thread(audit.recent, limit=100)
                fresh = [item for item in reversed(latest) if item.id not in seen]
                for item in fresh:
                    seen.add(item.id)
                    payload_json = json.dumps(
                        item.model_dump(mode="json"),
                        ensure_ascii=False,
                    )
                    yield f"data: {payload_json}\\n\\n"
                if len(seen) > 5000:
                    seen = {item.id for item in latest}
                yield ": keepalive\\n\\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    @router.get("/oauth-sessions")
    async def oauth_sessions(
        request: Request, limit: int = Query(200, ge=1, le=1000)
    ) -> JsonObject:
        require_user(request)
        items = await asyncio.to_thread(available().oauth_sessions.recent, limit=limit)
        return {"sessions": [_oauth_json(item) for item in items], "count": len(items)}

    @router.get("/files")
    async def files_list(
        request: Request,
        path: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(500, ge=1, le=1000),
    ) -> JsonObject:
        require_user(request)
        api = available()
        current = path.strip().strip("/")
        listing, cached_stats = await asyncio.gather(
            asyncio.to_thread(api.files.list, current, offset=offset, limit=limit),
            asyncio.to_thread(api.snapshots.get, WORKSPACE_STATS_KEY),
        )
        return {
            "listing": listing,
            "current_path": current,
            "parent_path": posixpath.dirname(current) if current else "",
            "stats": cached_stats.payload if cached_stats is not None else {},
            "stats_meta": snapshot_meta(cached_stats),
        }

    @router.post("/files/upload")
    async def files_upload(
        request: Request,
        file: Annotated[UploadFile, File()],
        path: Annotated[str, Form()] = "",
        overwrite: Annotated[bool, Form()] = False,
    ) -> JsonObject:
        api = mutation(request)
        current = path.strip().strip("/")
        name = Path(file.filename or "upload.bin").name
        destination = posixpath.join(current, name) if current else name
        try:
            result = await asyncio.to_thread(
                api.files.upload, file.file, destination=destination, overwrite=overwrite
            )
            await publish_management_event(api, "files.uploaded", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/files/mkdir")
    async def files_mkdir(
        request: Request, path: Annotated[str, Form()] = "", name: Annotated[str, Form()] = ""
    ) -> JsonObject:
        api = mutation(request)
        current = path.strip().strip("/")
        clean = name.strip().strip("/")
        if not clean or "/" in clean or "\\\\" in clean:
            raise HTTPException(status_code=400, detail="a single directory name is required")
        destination = posixpath.join(current, clean) if current else clean
        try:
            result = await asyncio.to_thread(api.files.mkdir, destination)
            await publish_management_event(api, "files.directory_created", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/files/download")
    async def files_download(request: Request, path: str) -> FileResponse:
        require_user(request)
        api = available()
        try:
            info = await asyncio.to_thread(api.files.info, path)
            file_path = await asyncio.to_thread(api.files.path_for, path)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if info.get("type") != "file":
            raise HTTPException(status_code=400, detail="path is not a file")
        return FileResponse(
            file_path,
            filename=str(info.get("name") or file_path.name),
            media_type=str(info.get("mime_type") or "application/octet-stream"),
        )

    @router.delete("/files")
    async def files_delete(request: Request, path: str, recursive: bool = False) -> JsonObject:
        api = mutation(request)
        try:
            result = await asyncio.to_thread(api.files.delete, path, recursive=recursive)
            await publish_management_event(api, "files.deleted", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/terminal")
    async def terminal_overview(request: Request) -> JsonObject:
        require_user(request)
        try:
            return await available().terminal.overview()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/terminal/jobs/{job_id}")
    async def terminal_job(job_id: str, request: Request) -> JsonObject:
        require_user(request)
        try:
            job, tail = await asyncio.gather(
                available().terminal.job_status(job_id), available().terminal.job_tail(job_id)
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"job": job, "tail": tail}

    @router.post("/terminal/jobs/{job_id}/cancel")
    async def terminal_cancel(job_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.terminal.cancel_job(job_id)
            await publish_management_event(api, "terminal.job.cancelled", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.delete("/terminal/jobs/{job_id}")
    async def terminal_delete_job(job_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.terminal.delete_job(job_id)
            await publish_management_event(api, "terminal.job.deleted", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/terminal/jobs/cleanup")
    async def terminal_cleanup(
        request: Request, older_than_hours: int = Query(168, ge=0, le=87600)
    ) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.terminal.cleanup_jobs(
                older_than_hours=older_than_hours, dry_run=False
            )
            await publish_management_event(api, "terminal.jobs.cleaned", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.delete("/terminal/workspaces/{workspace_id}")
    async def terminal_delete_workspace(workspace_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.terminal.delete_workspace(workspace_id)
            await publish_management_event(api, "terminal.workspace.deleted", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/analysis")
    async def analysis_overview(request: Request) -> JsonObject:
        require_user(request)
        snapshot = await asyncio.to_thread(available().snapshots.get, REVERSE_OVERVIEW_KEY)
        return {
            "overview": snapshot.payload if snapshot is not None else {},
            "meta": snapshot_meta(snapshot),
        }

    @router.get("/analysis/projects/{project_id:path}")
    async def analysis_project(project_id: str, request: Request, folder: str = "/") -> JsonObject:
        require_user(request)
        api = available()
        try:
            session = await api.reverse.session_info(project_id)
            files: JsonObject = {}
            programs: list[JsonValue] = []
            if session.get("session") == "active":
                files = await api.reverse.project_files(project_id, folder)
                programs = await api.reverse.open_programs(project_id)
            return {"session": session, "files": files, "programs": programs, "folder": folder}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/analysis/projects")
    async def analysis_create(payload: ProjectCreatePayload, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.reverse.create_project(payload.name, payload.parent_dir)
            await publish_management_event(api, "analysis.project.created", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/analysis/projects/{project_id:path}/open")
    async def analysis_open(project_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.reverse.open_session(project_id)
            await publish_management_event(api, "analysis.project.opened", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/analysis/projects/{project_id:path}/release")
    async def analysis_release(project_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.reverse.release_session(project_id)
            await publish_management_event(api, "analysis.project.released", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.delete("/analysis/projects/{project_id:path}")
    async def analysis_delete(project_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.reverse.delete_project(project_id)
            await publish_management_event(api, "analysis.project.deleted", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.put("/analysis/workers/{worker_index}")
    async def analysis_worker(
        worker_index: int, payload: WorkerControlPayload, request: Request
    ) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.reverse.set_worker_enabled(worker_index, payload.enabled)
            await publish_management_event(api, "analysis.worker.routing_changed", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def worker_state(api: WebApiServices, worker_index: int) -> JsonObject:
        overview = await api.reverse.overview()
        workers = overview.get("workers")
        if not isinstance(workers, list):
            workers = []
        for item in workers:
            if isinstance(item, dict) and item.get("worker_index") == worker_index:
                return json_object(item, context="analysis worker state")
        raise HTTPException(status_code=404, detail="worker not found")

    @router.get("/analysis/workers")
    async def analysis_workers(request: Request) -> JsonObject:
        require_user(request)
        try:
            overview = await available().reverse.overview()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        workers = overview.get("workers")
        items = workers if isinstance(workers, list) else []
        return {"workers": items, "count": len(items)}

    @router.get("/analysis/workers/{worker_index}")
    async def analysis_worker_state(worker_index: int, request: Request) -> JsonObject:
        require_user(request)
        try:
            return await worker_state(available(), worker_index)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/analysis/workers/{worker_index}/clear-queue")
    async def analysis_worker_clear_queue(worker_index: int, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.reverse.clear_worker_queue(worker_index)
            state = await worker_state(api, worker_index)
            response: JsonObject = {"operation": "clear_queue", "result": result, "worker": state}
            await publish_management_event(api, "analysis.worker.clear_queue", response)
            return response
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/analysis/workers/{worker_index}/recover")
    async def analysis_worker_recover(
        worker_index: int, payload: WorkerRecoverPayload, request: Request
    ) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.reverse.recover_worker(
                worker_index, timeout_seconds=payload.timeout_seconds
            )
            state = await worker_state(api, worker_index)
            response: JsonObject = {"operation": "recover", "result": result, "worker": state}
            await publish_management_event(api, "analysis.worker.recover", response)
            return response
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/analysis/projects/{project_id:path}/coverage")
    async def analysis_coverage(
        project_id: str, request: Request, program: str, full: bool = False
    ) -> JsonObject:
        require_user(request)
        api = available()
        key = coverage_snapshot_key(project_id, program, full=full)
        snapshot = await asyncio.to_thread(
            api.snapshots.ensure,
            key,
            category="reverse_coverage",
            parameters={"project_id": project_id, "program": program, "full": full},
            refresh_after_seconds=coverage_refresh_seconds(full=full),
        )
        api.snapshot_refresher.notify_coverage_requested()
        return {"coverage": snapshot.payload, "meta": snapshot_meta(snapshot)}

    @router.get("/browser/state")
    async def browser_state(request: Request) -> JsonObject:
        require_user(request)
        try:
            return await available().web.status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.put("/browser/viewport")
    async def browser_set_viewport(payload: ViewportPayload, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.web.set_viewport(payload.page_id, payload.width, payload.height)
            if api.realtime is not None:
                await api.realtime.publish("browser.runtime", "viewport.changed", result)
            return result
        except Exception as exc:
            message = str(exc)
            code = (
                404
                if "page" in message.casefold()
                and ("closed" in message.casefold() or "not found" in message.casefold())
                else 502
            )
            raise HTTPException(status_code=code, detail=message) from exc

    @router.post("/telemetry")
    async def frontend_telemetry(payload: FrontendTelemetryBatch, request: Request) -> JsonObject:
        api = mutation(request)
        if api.telemetry is None:
            raise HTTPException(status_code=503, detail="frontend telemetry unavailable")
        return api.telemetry.enqueue(list(payload.events))

    @router.get("/settings")
    async def settings_get(request: Request) -> JsonObject:
        require_user(request)
        api = available()
        config, terminal_policy, mcp_policy, github_policy = await asyncio.gather(
            asyncio.to_thread(api.config.get),
            asyncio.to_thread(api.runtime_settings.terminal_policy),
            asyncio.to_thread(api.runtime_settings.mcp_policy),
            asyncio.to_thread(api.runtime_settings.github_policy),
        )
        try:
            reverse_settings = await api.reverse.session_settings()
            reverse_error = ""
        except Exception as exc:
            reverse_settings = {
                "idle_timeout_seconds": 900.0,
                "auto_release_enabled": True,
                "source": "unavailable",
            }
            reverse_error = str(exc)
        return {
            "management": config.model_dump(mode="json"),
            "terminal": terminal_policy.model_dump(mode="json"),
            "mcp": mcp_policy.model_dump(mode="json"),
            "github": github_policy.model_dump(mode="json"),
            "analysis": reverse_settings,
            "analysis_error": reverse_error,
        }

    @router.put("/settings")
    async def settings_update(payload: SettingsPayload, request: Request) -> JsonObject:
        api = mutation(request)
        management = ManagementConfig(
            logging_enabled=payload.logging_enabled,
            logging_capture_payloads=payload.logging_capture_payloads,
            logging_retention_days=payload.logging_retention_days,
            logging_max_records=payload.logging_max_records,
            maintenance_interval_minutes=payload.maintenance_interval_minutes,
        )
        terminal_policy = TerminalRuntimePolicy(
            max_exec_timeout_seconds=payload.terminal_max_exec_timeout_seconds,
            max_job_runtime_seconds=payload.terminal_max_job_runtime_seconds,
        )
        mcp_policy = McpRuntimePolicy(call_timeout_seconds=payload.mcp_call_timeout_seconds)
        current_github = await asyncio.to_thread(api.runtime_settings.github_policy)
        github_policy = GitHubRuntimePolicy(
            local_first_guidance=(
                payload.github_local_first_guidance
                if "github_local_first_guidance" in payload.model_fields_set
                else current_github.local_first_guidance
            ),
            local_git_transport_enabled=(
                payload.github_local_git_transport_enabled
                if "github_local_git_transport_enabled" in payload.model_fields_set
                else current_github.local_git_transport_enabled
            ),
            remote_source_mutations_enabled=(
                payload.github_remote_source_mutations_enabled
                if "github_remote_source_mutations_enabled" in payload.model_fields_set
                else current_github.remote_source_mutations_enabled
            ),
        )
        try:
            reverse_settings = await api.reverse.set_idle_timeout(
                payload.reverse_idle_timeout_seconds
            )
            saved_management, saved_terminal, saved_mcp, saved_github = await asyncio.gather(
                asyncio.to_thread(api.config.update, management),
                asyncio.to_thread(api.runtime_settings.update_terminal_policy, terminal_policy),
                asyncio.to_thread(api.runtime_settings.update_mcp_policy, mcp_policy),
                asyncio.to_thread(api.runtime_settings.update_github_policy, github_policy),
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response: JsonObject = {
            "management": saved_management.model_dump(mode="json"),
            "terminal": saved_terminal.model_dump(mode="json"),
            "mcp": saved_mcp.model_dump(mode="json"),
            "github": saved_github.model_dump(mode="json"),
            "analysis": reverse_settings,
        }
        await publish_management_event(api, "settings.updated", response)
        return response

    @router.post("/settings/cleanup-logs")
    async def settings_cleanup(request: Request) -> JsonObject:
        api = mutation(request)
        removed = await asyncio.to_thread(api.audit.cleanup)
        response: JsonObject = {"removed": removed}
        await publish_management_event(api, "calls.retention_applied", response)
        return response

    return router
