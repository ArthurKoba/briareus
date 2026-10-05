from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import json
import posixpath
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Annotated, Literal

from application.services import (
    AccountService,
    AdminConfigService,
    InvocationAuditService,
    OAuthSessionService,
    RuntimeSettingsService,
    SnapshotService,
)
from dashboard_state import build_dashboard_state
from domain.accounts import Account, AccountConflictError, AuthType, Provider
from domain.configuration import AdminConfig
from domain.telemetry import InvocationQuery
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from infrastructure.authorization_access import AuthorizationAccessAdminClient
from infrastructure.authorization_identity import AuthorizationIdentityClient, LocalUserIdentity
from infrastructure.files import FileAdminStore
from infrastructure.reverse import ReverseAdminClient
from infrastructure.snapshot_worker import (
    REVERSE_OVERVIEW_KEY,
    WORKSPACE_STATS_KEY,
    SnapshotRefresher,
    coverage_refresh_seconds,
    coverage_snapshot_key,
    snapshot_meta,
)
from infrastructure.terminal import TerminalAdminClient
from infrastructure.web import WebAdminClient
from origin import origin_allowed
from pydantic import BaseModel, ConfigDict, Field
from realtime import RealtimeBus
from starlette.responses import FileResponse, Response, StreamingResponse
from telemetry_ingest import FrontendTelemetryProxy

from common.access_contracts import AccessLevel, AccountScope, EnforcementMode
from common.browser_remote_debug import (
    BROWSER_REMOTE_DEBUG_TTL_SECONDS,
    issue_browser_remote_debug_token,
)
from common.models import JsonObject, JsonValue, json_object
from common.runtime_policy_contracts import (
    GitHubRuntimePolicy,
    GitLabRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)
from common.settings import AdminApiSettings

_SESSION_KEY = "admin_api_session"


def _encode_call_cursor(occurred_at: datetime, invocation_id: str) -> str:
    payload = json.dumps(
        [occurred_at.astimezone(UTC).isoformat(), invocation_id],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_call_cursor(value: str) -> tuple[datetime, str]:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if not isinstance(decoded, list) or len(decoded) != 2:
            raise ValueError("invalid cursor payload")
        occurred_at = datetime.fromisoformat(str(decoded[0]))
        invocation_id = str(decoded[1]).strip()
        if not invocation_id:
            raise ValueError("invalid cursor id")
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        else:
            occurred_at = occurred_at.astimezone(UTC)
        return occurred_at, invocation_id
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="invalid calls cursor") from exc


@dataclass(frozen=True)
class WebApiServices:
    accounts: AccountService
    audit: InvocationAuditService
    oauth_sessions: OAuthSessionService
    snapshots: SnapshotService
    config: AdminConfigService
    runtime_settings: RuntimeSettingsService
    files: FileAdminStore
    reverse: ReverseAdminClient
    terminal: TerminalAdminClient
    web: WebAdminClient
    snapshot_refresher: SnapshotRefresher
    realtime: RealtimeBus | None = None
    telemetry: FrontendTelemetryProxy | None = None
    authorization_access: AuthorizationAccessAdminClient | None = None
    authorization_identity: AuthorizationIdentityClient | None = None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str


class AccessResolvePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: bool
    account_scope: AccountScope | None = None
    account_ids: list[str] | None = None
    expires_at: int | None = Field(default=None, ge=0)


class AccessSessionUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_level: AccessLevel | None = None
    account_scope: AccountScope | None = None
    account_ids: list[str] | None = None
    expires_at: int | None = Field(default=None, ge=0)
    label: str | None = Field(default=None, max_length=256)


class AccessControlItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    surface_id: int
    mode: EnforcementMode


class AccessControlBatchPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[AccessControlItem] = Field(min_length=1, max_length=100)


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


class AccountUpdatePayload(AccountPayload):
    expected_updated_at: datetime | None = None


class AccountCandidatePayload(AccountPayload):
    alias: str = Field(min_length=1, max_length=128)
    base_url: str = Field("", max_length=2048)
    external_id: str = Field("", max_length=512)
    ca_cert_pem: str = Field("", max_length=65_536)
    credential: str = Field("", max_length=131_072)
    account_id: str = Field("", max_length=36)
    draft_revision: str = Field(min_length=1, max_length=128)


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


class BrowserThemePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    color_scheme: str = Field(pattern="^(system|light|dark)$")


class BrowserRemoteDebugPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_id: str = Field(min_length=1, max_length=255)


class FrontendTelemetryBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[JsonValue] = Field(min_length=1, max_length=500)


class SettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field("", max_length=64)
    logging_enabled: bool = True
    logging_capture_payloads: bool = True
    logging_retention_days: int = Field(30, ge=1, le=3650)
    logging_max_records: int = Field(10_000, ge=100, le=1_000_000)
    maintenance_interval_minutes: int = Field(60, ge=1, le=1440)
    terminal_max_exec_timeout_seconds: int = Field(21_600, ge=1, le=86_400)
    terminal_max_job_runtime_seconds: int = Field(43_200, ge=1, le=604_800)
    mcp_call_timeout_seconds: int = Field(5, ge=1, le=300)
    github_local_first_guidance: bool = True
    github_local_git_transport_enabled: bool = True
    github_remote_source_mutations_enabled: bool = False
    gitlab_local_first_guidance: bool = True
    gitlab_local_git_transport_enabled: bool = True
    gitlab_remote_source_mutations_enabled: bool = False
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
    settings: AdminApiSettings, services: WebApiServices | None = None
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["admin"])
    settings_update_lock = asyncio.Lock()
    candidate_verify_slots = asyncio.Semaphore(4)
    candidate_verify_rate_lock = asyncio.Lock()
    candidate_verify_attempts: dict[str, deque[float]] = {}

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
        if not origin_allowed(origin, public_host, settings.admin_ui_origin):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="origin rejected")

    def available() -> WebApiServices:
        if services is None:
            raise HTTPException(status_code=503, detail="admin API services unavailable")
        return services

    def mutation(request: Request) -> WebApiServices:
        require_user(request)
        same_origin(request)
        return available()

    async def local_user(request: Request) -> LocalUserIdentity:
        username = require_user(request)
        api = available()
        if api.authorization_identity is None:
            raise HTTPException(
                status_code=503, detail="authorization identity service unavailable"
            )
        try:
            identity = await api.authorization_identity.by_username(username)
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="authorization identity service unavailable"
            ) from exc
        if not identity.enabled:
            raise HTTPException(status_code=403, detail="local user disabled")
        return identity

    def authorization_access_control(api: WebApiServices) -> AuthorizationAccessAdminClient:
        if api.authorization_access is None:
            raise HTTPException(status_code=503, detail="authorization controls unavailable")
        return api.authorization_access

    async def publish_admin_event(api: WebApiServices, event_type: str, data: object) -> None:
        if api.realtime is not None:
            await api.realtime.publish("admin.events", event_type, data)

    async def enforce_candidate_verify_rate(request: Request) -> None:
        username = authenticated_username(request) or "unknown"
        client_host = request.client.host if request.client is not None else "unknown"
        key = f"{username}:{client_host}"
        now = monotonic()
        cutoff = now - 60.0
        async with candidate_verify_rate_lock:
            bucket = candidate_verify_attempts.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= 20:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="candidate verification rate limit exceeded",
                    headers={"Retry-After": "60"},
                )
            bucket.append(now)

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
            "product": "MCP Admin API",
            "environment": "runtime",
            "navigation": [
                {"id": "overview", "label": "Overview", "enabled": True},
                {"id": "accounts", "label": "Accounts", "enabled": True},
                {"id": "calls", "label": "MCP Calls", "enabled": True},
                {"id": "files", "label": "Files", "enabled": True},
                {"id": "terminal", "label": "Terminal", "enabled": True},
                {"id": "browser", "label": "Browser", "enabled": True},
                {"id": "analysis", "label": "Analysis", "enabled": True},
                {"id": "access", "label": "Access", "enabled": True},
                {"id": "oauth", "label": "OAuth Sessions", "enabled": True},
                {"id": "settings", "label": "Settings", "enabled": True},
            ],
        }

    @router.get("/access/sessions")
    async def access_sessions(request: Request) -> JsonObject:
        identity = await local_user(request)
        api = available()
        return json_object(
            {
                "user": identity.model_dump(mode="json"),
                "sessions": await authorization_access_control(api).sessions(identity.id),
            }
        )

    @router.get("/access/requests")
    async def access_requests(request: Request) -> JsonObject:
        identity = await local_user(request)
        api = available()
        return json_object(
            {
                "user": identity.model_dump(mode="json"),
                "requests": await authorization_access_control(api).requests(identity.id),
            }
        )

    @router.get("/access/controls")
    async def access_controls(request: Request) -> JsonObject:
        identity = await local_user(request)
        api = available()
        return json_object(
            {
                "user": identity.model_dump(mode="json"),
                "controls": await authorization_access_control(api).controls(identity.id),
            }
        )

    @router.post("/access/requests/{request_id}/resolve")
    async def resolve_access_request(
        request_id: str, payload: AccessResolvePayload, request: Request
    ) -> JsonObject:
        api = mutation(request)
        identity = await local_user(request)
        result = await authorization_access_control(api).resolve_request(
            request_id,
            admin_user_id=identity.id,
            approve=payload.approve,
            account_scope=payload.account_scope,
            account_ids=payload.account_ids,
            expires_at=payload.expires_at,
        )
        if api.realtime is not None:
            await api.realtime.publish("access.sessions", "request_resolved", result)
        return json_object(result)

    @router.patch("/access/sessions/{session_id}")
    async def update_access_session(
        session_id: str, payload: AccessSessionUpdatePayload, request: Request
    ) -> JsonObject:
        api = mutation(request)
        identity = await local_user(request)
        result = await authorization_access_control(api).update_session(
            session_id,
            admin_user_id=identity.id,
            access_level=payload.access_level,
            account_scope=payload.account_scope,
            account_ids=payload.account_ids,
            expires_at=payload.expires_at,
            label=payload.label,
        )
        if api.realtime is not None:
            await api.realtime.publish("access.sessions", "session_updated", result)
        return result

    @router.post("/access/sessions/{session_id}/revoke", status_code=204)
    async def revoke_access_session(session_id: str, request: Request) -> Response:
        api = mutation(request)
        identity = await local_user(request)
        await authorization_access_control(api).revoke_session(
            session_id, admin_user_id=identity.id
        )
        if api.realtime is not None:
            await api.realtime.publish(
                "access.sessions", "session_revoked", {"session_id": session_id}
            )
        return Response(status_code=204)

    @router.put("/access/controls")
    async def update_access_controls(
        payload: AccessControlBatchPayload, request: Request
    ) -> JsonObject:
        api = mutation(request)
        identity = await local_user(request)
        controls = await authorization_access_control(api).set_controls(
            user_id=identity.id,
            items=[(item.surface_id, item.mode) for item in payload.items],
        )
        result = json_object(
            {
                "user": identity.model_dump(mode="json"),
                "controls": controls,
            }
        )
        if api.realtime is not None:
            await api.realtime.publish("access.sessions", "controls_changed", result)
        return result

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
        items = await available().accounts.list(provider=provider)
        return {"accounts": [item.model_dump(mode="json") for item in items], "count": len(items)}

    @router.post("/accounts", status_code=201)
    async def create_account(payload: AccountPayload, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            account = _account_from_payload(payload)
            saved = await api.accounts.create(account, credential=payload.credential)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return saved.public()

    @router.put("/accounts/{provider}/{account_id}")
    async def update_account(
        provider: Provider, account_id: str, payload: AccountUpdatePayload, request: Request
    ) -> JsonObject:
        api = mutation(request)
        if payload.provider is not provider:
            raise HTTPException(status_code=400, detail="provider cannot be changed")
        try:
            existing = await api.accounts.get(account_id, provider=provider, enabled_only=False)
            if payload.expected_updated_at is not None:
                expected = payload.expected_updated_at
                if expected.tzinfo is None:
                    expected = expected.replace(tzinfo=UTC)
                else:
                    expected = expected.astimezone(UTC)
                persisted = existing.updated_at
                if persisted.tzinfo is None:
                    persisted = persisted.replace(tzinfo=UTC)
                else:
                    persisted = persisted.astimezone(UTC)
                if expected != persisted:
                    raise AccountConflictError("account changed since it was loaded")
            saved = await api.accounts.update(
                _account_from_payload(payload, existing=existing),
                credential=payload.credential,
                expected_updated_at=existing.updated_at if payload.expected_updated_at else None,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AccountConflictError as exc:
            try:
                current = await api.accounts.get(account_id, provider=provider, enabled_only=False)
                current_updated_at: str | None = str(current.public()["updated_at"])
            except KeyError:
                current_updated_at = None
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "account_conflict",
                    "message": "account changed since it was loaded; reload before saving",
                    "current_updated_at": current_updated_at,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return saved.public()

    @router.delete("/accounts/{provider}/{account_id}")
    async def delete_account(provider: Provider, account_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            await api.accounts.delete(account_id, provider=provider)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True, "id": account_id, "provider": provider.value}

    @router.post("/accounts/verify-candidate")
    async def verify_account_candidate(
        payload: AccountCandidatePayload, request: Request
    ) -> JsonObject:
        api = mutation(request)
        await enforce_candidate_verify_rate(request)
        existing: Account | None = None
        try:
            if payload.account_id:
                existing = await api.accounts.get(
                    payload.account_id,
                    provider=payload.provider,
                    enabled_only=False,
                )
            account = _account_from_payload(payload, existing=existing)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="account not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if not payload.credential.strip() and existing is None:
            raise HTTPException(status_code=400, detail="credential is required for a new account")

        try:
            async with candidate_verify_slots:
                result = await asyncio.wait_for(
                    api.accounts.verify_candidate(
                        account,
                        credential=payload.credential,
                        credential_account_id=existing.id if existing is not None else "",
                    ),
                    timeout=20.0,
                )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="candidate verification timed out",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="candidate verification failed",
            ) from exc
        if result.get("ok") is not True:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="candidate verification failed",
            )
        return {
            "ok": True,
            "provider": payload.provider.value,
            "draft_revision": payload.draft_revision,
        }

    @router.post("/accounts/{provider}/{account_id}/verify")
    async def verify_account(provider: Provider, account_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            return await api.accounts.verify(account_id, provider=provider)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/calls")
    async def calls(
        request: Request,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        cursor: str = Query("", max_length=512),
        module: str = Query("", max_length=64),
        tool: str = Query("", max_length=256),
        provider: str = Query("", max_length=32),
        account_id: str = Query("", max_length=128),
        call_status: Literal["success", "error"] | None = Query(None, alias="status"),
        search: str = Query("", max_length=256),
    ) -> JsonObject:
        require_user(request)
        cursor_at: datetime | None = None
        cursor_id = ""
        if cursor:
            cursor_at, cursor_id = _decode_call_cursor(cursor)
        page = await available().audit.query(
            InvocationQuery(
                limit=limit,
                offset=offset,
                cursor_at=cursor_at,
                cursor_id=cursor_id,
                module=module.strip(),
                tool=tool.strip(),
                provider=provider.strip(),
                account_id=account_id.strip(),
                status=call_status,
                search=search.strip(),
            )
        )
        next_cursor = (
            _encode_call_cursor(page.next_cursor_at, page.next_cursor_id)
            if page.next_cursor_at is not None and page.next_cursor_id
            else ""
        )
        return {
            "events": [item.model_dump(mode="json") for item in page.events],
            "count": page.count,
            "total": page.total,
            "limit": limit,
            "offset": offset,
            "has_more": page.has_more,
            "next_cursor": next_cursor,
        }

    @router.delete("/calls")
    async def clear_calls(request: Request) -> JsonObject:
        api = mutation(request)
        removed = await api.audit.clear()
        response: JsonObject = {"deleted": removed}
        await publish_admin_event(api, "calls.cleared", response)
        return response

    @router.delete("/calls/{call_id}")
    async def delete_call(call_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        removed = await api.audit.delete(call_id)
        if not removed:
            raise HTTPException(status_code=404, detail="call not found")
        response: JsonObject = {"deleted": True, "id": call_id}
        await publish_admin_event(api, "calls.deleted", response)
        return response

    @router.get("/calls/stream")
    async def calls_stream(request: Request) -> StreamingResponse:
        require_user(request)
        audit = available().audit

        async def events() -> AsyncIterator[str]:
            seen: set[str] = set()
            initial = await audit.recent(limit=100)
            for item in reversed(initial):
                seen.add(item.id)
                yield f"data: {json.dumps(item.model_dump(mode='json'), ensure_ascii=False)}\\n\\n"
            while not await request.is_disconnected():
                latest = await audit.recent(limit=100)
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
        items = await available().oauth_sessions.recent(limit=limit)
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
            api.snapshots.get(WORKSPACE_STATS_KEY),
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
            await publish_admin_event(api, "files.uploaded", result)
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
            await publish_admin_event(api, "files.directory_created", result)
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
            await publish_admin_event(api, "files.deleted", result)
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
            await publish_admin_event(api, "terminal.job.cancelled", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.delete("/terminal/jobs/{job_id}")
    async def terminal_delete_job(job_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.terminal.delete_job(job_id)
            await publish_admin_event(api, "terminal.job.deleted", result)
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
            await publish_admin_event(api, "terminal.jobs.cleaned", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.delete("/terminal/workspaces/{workspace_id}")
    async def terminal_delete_workspace(workspace_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.terminal.delete_workspace(workspace_id)
            await publish_admin_event(api, "terminal.workspace.deleted", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/analysis")
    async def analysis_overview(request: Request) -> JsonObject:
        require_user(request)
        snapshot = await available().snapshots.get(REVERSE_OVERVIEW_KEY)
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
            await publish_admin_event(api, "analysis.project.created", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/analysis/projects/{project_id:path}/open")
    async def analysis_open(project_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.reverse.open_session(project_id)
            await publish_admin_event(api, "analysis.project.opened", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/analysis/projects/{project_id:path}/release")
    async def analysis_release(project_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.reverse.release_session(project_id)
            await publish_admin_event(api, "analysis.project.released", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.delete("/analysis/projects/{project_id:path}")
    async def analysis_delete(project_id: str, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.reverse.delete_project(project_id)
            await publish_admin_event(api, "analysis.project.deleted", result)
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
            await publish_admin_event(api, "analysis.worker.routing_changed", result)
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
            await publish_admin_event(api, "analysis.worker.clear_queue", response)
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
            await publish_admin_event(api, "analysis.worker.recover", response)
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
        snapshot = await api.snapshots.ensure(
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

    @router.put("/browser/theme")
    async def browser_set_theme(payload: BrowserThemePayload, request: Request) -> JsonObject:
        api = mutation(request)
        try:
            result = await api.web.set_theme(payload.color_scheme)
            if api.realtime is not None:
                await api.realtime.publish("browser.runtime", "theme.changed", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/browser/remote-debug")
    async def browser_remote_debug(
        payload: BrowserRemoteDebugPayload, request: Request
    ) -> JsonObject:
        api = mutation(request)
        try:
            target = await api.web.debug_target(payload.page_id)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        target_id = str(target.get("target_id") or "")
        if not target_id:
            raise HTTPException(status_code=502, detail="browser target is unavailable")
        token = issue_browser_remote_debug_token(
            settings.service_token, settings.admin_username, target_id
        )
        public_host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        if not public_host:
            raise HTTPException(status_code=500, detail="public host is unavailable")
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme).casefold()
        secure = forwarded_proto == "https"
        websocket_scheme = "wss" if secure else "ws"
        http_scheme = "https" if secure else "http"
        devtools_parameter = "wss" if secure else "ws"
        remote_path = f"/v1/browser/cdp/{token}/page/{target_id}"
        frontend_path = f"/v1/browser/devtools/{token}/page/{target_id}/devtools/inspector.html"
        response: JsonObject = {
            **target,
            "expires_in_seconds": BROWSER_REMOTE_DEBUG_TTL_SECONDS,
            "websocket_url": f"{websocket_scheme}://{public_host}{remote_path}",
            "frontend_url": (
                f"{http_scheme}://{public_host}{frontend_path}?"
                f"{devtools_parameter}={public_host}{remote_path}"
            ),
            "devtools_url": (
                "devtools://devtools/bundled/inspector.html?"
                f"{devtools_parameter}={public_host}{remote_path}"
            ),
        }
        if api.realtime is not None:
            await api.realtime.publish(
                "browser.runtime",
                "remote_debug.issued",
                {"page_id": payload.page_id, "target_id": target_id},
            )
        return response

    @router.get("/browser/devtools/{token}/page/{target_id}/{asset_path:path}")
    async def browser_devtools_asset(
        token: str,
        target_id: str,
        asset_path: str,
        request: Request,
    ) -> Response:
        api = available()
        try:
            status_code, headers, body = await api.web.devtools_asset(
                token,
                target_id,
                asset_path,
                request.url.query,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return Response(content=body, status_code=status_code, headers=headers, media_type=None)

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

    def settings_revision(snapshot: JsonObject) -> str:
        analysis = json_object(snapshot["analysis"], context="analysis settings")
        idle_raw = analysis.get("idle_timeout_seconds", 900.0)
        idle_timeout = float(idle_raw) if isinstance(idle_raw, (int, float)) else 900.0
        versioned = {
            "admin": snapshot["admin"],
            "terminal": snapshot["terminal"],
            "mcp": snapshot["mcp"],
            "github": snapshot["github"],
            "gitlab": snapshot["gitlab"],
            "analysis_idle_timeout_seconds": idle_timeout,
        }
        encoded = json.dumps(versioned, sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()

    async def settings_snapshot(api: WebApiServices) -> JsonObject:
        config, terminal_policy, mcp_policy, github_policy, gitlab_policy = await asyncio.gather(
            api.config.get(),
            api.runtime_settings.terminal_policy(),
            api.runtime_settings.mcp_policy(),
            api.runtime_settings.github_policy(),
            api.runtime_settings.gitlab_policy(),
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
        snapshot: JsonObject = {
            "admin": config.model_dump(mode="json"),
            "terminal": terminal_policy.model_dump(mode="json"),
            "mcp": mcp_policy.model_dump(mode="json"),
            "github": github_policy.model_dump(mode="json"),
            "gitlab": gitlab_policy.model_dump(mode="json"),
            "analysis": reverse_settings,
            "analysis_error": reverse_error,
        }
        snapshot["revision"] = settings_revision(snapshot)
        return snapshot

    @router.get("/settings")
    async def settings_get(request: Request) -> JsonObject:
        require_user(request)
        return await settings_snapshot(available())

    @router.put("/settings")
    async def settings_update(payload: SettingsPayload, request: Request) -> JsonObject:
        api = mutation(request)
        async with settings_update_lock:
            current: JsonObject | None = None
            if payload.expected_revision:
                try:
                    current = await settings_snapshot(api)
                except (ValueError, RuntimeError) as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                if payload.expected_revision != current["revision"]:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "settings_conflict",
                            "message": (
                                "settings changed since they were loaded; reload before saving"
                            ),
                            "current_revision": current["revision"],
                        },
                    )
            admin_api = AdminConfig(
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
            github_fields = {
                "github_local_first_guidance",
                "github_local_git_transport_enabled",
                "github_remote_source_mutations_enabled",
            }
            try:
                if github_fields.issubset(payload.model_fields_set):
                    github_policy = GitHubRuntimePolicy(
                        local_first_guidance=payload.github_local_first_guidance,
                        local_git_transport_enabled=payload.github_local_git_transport_enabled,
                        remote_source_mutations_enabled=payload.github_remote_source_mutations_enabled,
                    )
                else:
                    if current is not None:
                        current_github = GitHubRuntimePolicy.model_validate(current["github"])
                    else:
                        current_github = await api.runtime_settings.github_policy()
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
                gitlab_fields = {
                    "gitlab_local_first_guidance",
                    "gitlab_local_git_transport_enabled",
                    "gitlab_remote_source_mutations_enabled",
                }
                if gitlab_fields.issubset(payload.model_fields_set):
                    gitlab_policy = GitLabRuntimePolicy(
                        local_first_guidance=payload.gitlab_local_first_guidance,
                        local_git_transport_enabled=payload.gitlab_local_git_transport_enabled,
                        remote_source_mutations_enabled=payload.gitlab_remote_source_mutations_enabled,
                    )
                else:
                    if current is not None:
                        current_gitlab = GitLabRuntimePolicy.model_validate(current["gitlab"])
                    else:
                        current_gitlab = await api.runtime_settings.gitlab_policy()
                    gitlab_policy = GitLabRuntimePolicy(
                        local_first_guidance=(
                            payload.gitlab_local_first_guidance
                            if "gitlab_local_first_guidance" in payload.model_fields_set
                            else current_gitlab.local_first_guidance
                        ),
                        local_git_transport_enabled=(
                            payload.gitlab_local_git_transport_enabled
                            if "gitlab_local_git_transport_enabled" in payload.model_fields_set
                            else current_gitlab.local_git_transport_enabled
                        ),
                        remote_source_mutations_enabled=(
                            payload.gitlab_remote_source_mutations_enabled
                            if "gitlab_remote_source_mutations_enabled" in payload.model_fields_set
                            else current_gitlab.remote_source_mutations_enabled
                        ),
                    )
                reverse_settings = await api.reverse.set_idle_timeout(
                    payload.reverse_idle_timeout_seconds
                )
                (
                    saved_admin,
                    saved_terminal,
                    saved_mcp,
                    saved_github,
                    saved_gitlab,
                ) = await asyncio.gather(
                    api.config.update(admin_api),
                    api.runtime_settings.update_terminal_policy(terminal_policy),
                    api.runtime_settings.update_mcp_policy(mcp_policy),
                    api.runtime_settings.update_github_policy(github_policy),
                    api.runtime_settings.update_gitlab_policy(gitlab_policy),
                )
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            response: JsonObject = {
                "admin": saved_admin.model_dump(mode="json"),
                "terminal": saved_terminal.model_dump(mode="json"),
                "mcp": saved_mcp.model_dump(mode="json"),
                "github": saved_github.model_dump(mode="json"),
                "gitlab": saved_gitlab.model_dump(mode="json"),
                "analysis": reverse_settings,
                "analysis_error": "",
            }
            response["revision"] = settings_revision(response)
            await publish_admin_event(api, "settings.updated", response)
            return response

    @router.post("/settings/cleanup-logs")
    async def settings_cleanup(request: Request) -> JsonObject:
        api = mutation(request)
        removed = await api.audit.cleanup()
        response: JsonObject = {"removed": removed}
        await publish_admin_event(api, "calls.retention_applied", response)
        return response

    return router
