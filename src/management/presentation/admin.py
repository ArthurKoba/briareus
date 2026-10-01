from __future__ import annotations

import asyncio
import hmac
import posixpath
import urllib.parse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.base import Executable
from sqlalchemy.sql.elements import ColumnElement
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse, Response
from starlette.templating import Jinja2Templates
from starlette_admin import (
    BooleanField,
    Breakpoints,
    CardRowWidget,
    Col,
    CustomView,
    DateTimeField,
    EnumField,
    PasswordField,
    RowActionsDisplayType,
    StatWidget,
    StringField,
    TextAreaField,
    action,
    flash,
    route,
)
from starlette_admin.actions import row_action
from starlette_admin.auth import AdminUser, AuthProvider, LoginFailed
from starlette_admin.contrib.sqla import Admin, ModelView
from starlette_admin.exceptions import ActionFailed
from starlette_admin.fields import BaseField

from common.models import JsonObject, JsonValue, json_int, json_str
from common.public_tool_names import public_tool_name
from common.settings import ManagementSettings
from management.application.services import (
    AccountService,
    InvocationAuditService,
    ManagementConfigService,
    OAuthSessionService,
)
from management.domain.accounts import Account, AuthType, Provider
from management.domain.configuration import ManagementConfig
from management.infrastructure.crypto import FernetCredentialCipher
from management.infrastructure.database import (
    GitHubAccountRecord,
    GitLabAccountRecord,
    InvocationRecord,
    OAuthSessionRecord,
)
from management.infrastructure.files import FileAdminStore
from management.infrastructure.reverse import ReverseAdminClient
from management.infrastructure.terminal import TerminalAdminClient
from management.presentation.admin_ui import ManagementUiPlugin


class ManagementAuthProvider(AuthProvider):
    def __init__(self, settings: ManagementSettings) -> None:
        super().__init__()
        self.settings = settings

    async def login(
        self,
        username: str,
        password: str,
        remember_me: bool,
        request: Request,
    ) -> None:
        del remember_me
        valid_user = hmac.compare_digest(username, self.settings.admin_username)
        valid_password = hmac.compare_digest(password, self.settings.admin_password)
        if not (valid_user and valid_password):
            raise LoginFailed("Invalid username or password")
        request.session["management_admin"] = self.settings.admin_username

    async def authenticate(self, request: Request) -> AdminUser | None:
        username = request.session.get("management_admin")
        if not isinstance(username, str) or not username:
            return None
        return AdminUser(username=username)

    async def logout(self, request: Request) -> None:
        request.session.clear()


class _BaseAccountView(ModelView):
    row_actions = ("view", "edit", "test_connection", "delete")
    row_actions_display_type = RowActionsDisplayType.KEBAB
    page_size = 25
    search_auto_submit = True
    exclude_fields_from_create = ("id", "encrypted_credential", "created_at", "updated_at")
    exclude_fields_from_edit = ("id", "encrypted_credential", "created_at", "updated_at")

    provider: Provider

    def __init__(
        self,
        model: type[GitHubAccountRecord] | type[GitLabAccountRecord],
        cipher: FernetCredentialCipher,
        accounts: AccountService,
        *,
        icon: str,
        menu_label: str,
    ) -> None:
        super().__init__(
            model,
            icon=icon,
            menu_label=menu_label,
            display_name=menu_label.rstrip("s"),
        )
        self.cipher = cipher
        self.accounts = accounts
        self.page_size_options = [25, 50, 100]

    def _validated(self, obj: GitHubAccountRecord | GitLabAccountRecord) -> Account:
        if self.provider is Provider.GITHUB:
            github_record = cast(GitHubAccountRecord, obj)
            return Account(
                id=github_record.id,
                alias=github_record.alias,
                provider=Provider.GITHUB,
                auth_type=AuthType(github_record.auth_type),
                external_id=github_record.app_id,
                enabled=github_record.enabled,
                created_at=github_record.created_at,
                updated_at=github_record.updated_at,
            )
        gitlab_record = cast(GitLabAccountRecord, obj)
        return Account(
            id=gitlab_record.id,
            alias=gitlab_record.alias,
            provider=Provider.GITLAB,
            auth_type=AuthType(gitlab_record.auth_type),
            base_url=gitlab_record.base_url,
            verify_tls=gitlab_record.verify_tls,
            ca_cert_pem=gitlab_record.ca_cert_pem,
            enabled=gitlab_record.enabled,
            created_at=gitlab_record.created_at,
            updated_at=gitlab_record.updated_at,
        )

    def _apply_normalized(
        self,
        obj: GitHubAccountRecord | GitLabAccountRecord,
        account: Account,
    ) -> None:
        obj.alias = account.alias
        obj.auth_type = account.auth_type.value
        obj.enabled = account.enabled
        if self.provider is Provider.GITHUB:
            cast(GitHubAccountRecord, obj).app_id = account.external_id
            return
        record = cast(GitLabAccountRecord, obj)
        record.base_url = account.base_url
        record.verify_tls = account.verify_tls
        record.ca_cert_pem = account.ca_cert_pem

    async def before_create(
        self,
        request: Request,
        data: dict[str, object],
        obj: GitHubAccountRecord | GitLabAccountRecord,
    ) -> None:
        del request, data
        secret = obj._credential_input.strip()
        if not secret:
            raise ValueError("credential is required when creating an account")
        now = datetime.now(UTC)
        if not obj.id:
            obj.id = str(uuid4())
        obj.created_at = now
        obj.updated_at = now
        account = self._validated(obj)
        self._apply_normalized(obj, account)
        obj.encrypted_credential = self.cipher.encrypt(secret)
        obj._credential_input = ""

    async def before_edit(
        self,
        request: Request,
        data: dict[str, object],
        obj: GitHubAccountRecord | GitLabAccountRecord,
    ) -> None:
        del request, data
        obj.updated_at = datetime.now(UTC)
        account = self._validated(obj)
        self._apply_normalized(obj, account)
        secret = obj._credential_input.strip()
        if secret:
            obj.encrypted_credential = self.cipher.encrypt(secret)
        obj._credential_input = ""

    @row_action(name="test_connection", text="Test connection", icon_class="fa fa-plug")
    async def test_connection(self, request: Request, pk: object) -> None:
        try:
            result = self.accounts.verify(str(pk), provider=self.provider)
        except Exception as exc:
            raise ActionFailed(str(exc)) from exc
        provider = str(result.get("provider", self.provider.value))
        flash(request, f"{provider} connection verified successfully", "success")


class GitHubAccountView(_BaseAccountView):
    provider = Provider.GITHUB
    fields = cast(
        Sequence[BaseField],
        (
            "id",
            "alias",
            EnumField(
                "auth_type",
                choices=[
                    (AuthType.GITHUB_APP.value, "GitHub App"),
                    (AuthType.GITHUB_TOKEN.value, "Personal / user token"),
                ],
                required=True,
            ),
            "app_id",
            BooleanField("enabled", default=True),
            PasswordField(
                "credential_input",
                label="Token / private key",
                required=False,
                exclude_from_list=True,
                exclude_from_detail=True,
                getter=lambda _request, _obj: "",
                help_text=(
                    "GitHub App: private key PEM and App ID. Token account: PAT/user token; "
                    "App ID is ignored. Leave blank on edit to keep the stored credential."
                ),
            ),
            "created_at",
            "updated_at",
        ),
    )
    searchable_fields = ("alias", "app_id")


class GitLabAccountView(_BaseAccountView):
    provider = Provider.GITLAB
    fields = cast(
        Sequence[BaseField],
        (
            "id",
            "alias",
            "base_url",
            EnumField(
                "auth_type",
                choices=[
                    (AuthType.PRIVATE_TOKEN.value, "Private token"),
                    (AuthType.BEARER.value, "OAuth / bearer token"),
                    (AuthType.JOB_TOKEN.value, "Job token"),
                ],
                required=True,
            ),
            "verify_tls",
            TextAreaField("ca_cert_pem", label="Custom CA certificate PEM"),
            BooleanField("enabled", default=True),
            PasswordField(
                "credential_input",
                label="Access token",
                required=False,
                exclude_from_list=True,
                exclude_from_detail=True,
                getter=lambda _request, _obj: "",
                help_text="Leave blank on edit to keep the stored token.",
            ),
            "created_at",
            "updated_at",
        ),
    )
    searchable_fields = ("alias", "base_url")


def _display_invocation_tool(_request: Request, obj: InvocationRecord) -> str:
    return public_tool_name(obj.module, obj.tool)


def _display_invocation_duration(_request: Request, obj: InvocationRecord) -> str:
    return f"{obj.duration_ms:.1f} ms"


class InvocationView(ModelView):
    row_actions_display_type = RowActionsDisplayType.KEBAB
    page_size = 50
    fields = cast(
        Sequence[BaseField],
        (
            "module",
            StringField("tool", label="Tool", getter=_display_invocation_tool),
            DateTimeField("occurred_at", label="Time"),
            StringField("duration_ms", label="Duration", getter=_display_invocation_duration),
            "status",
            "provider",
            "error_type",
            "account_id",
            "request_id",
            StringField("id", label="Call ID"),
            TextAreaField("arguments_json", label="Arguments"),
            TextAreaField("result_json", label="Result"),
            TextAreaField("error_message", label="Error message"),
        ),
    )
    fields_default_sort = (("occurred_at", True),)
    searchable_fields = ("module", "tool", "provider", "account_id", "error_type", "request_id")
    exclude_fields_from_list = ("arguments_json", "result_json", "error_message")
    actions = ("clear_all", "delete")

    def __init__(self, model: type[InvocationRecord], audit: InvocationAuditService) -> None:
        super().__init__(
            model,
            icon="fa fa-chart-line",
            menu_label="MCP Calls",
            display_name="MCP Call",
        )
        self.audit = audit
        self.page_size_options = [25, 50, 100]

    def can_create(self, _request: Request) -> bool:
        return False

    def can_edit(self, _request: Request) -> bool:
        return False

    @action(
        name="clear_all",
        text="Clear all logs",
        confirmation="Delete all MCP invocation logs?",
        allow_empty_selection=True,
        dedicated_button=True,
    )
    async def clear_all(self, request: Request, _selection: object) -> None:
        removed = await asyncio.to_thread(self.audit.clear)
        flash(request, f"Deleted {removed} invocation log records", "success")


class OAuthSessionView(ModelView):
    row_actions_display_type = RowActionsDisplayType.KEBAB
    page_size = 50
    fields = cast(
        Sequence[BaseField],
        (
            "status",
            "login",
            "resource",
            "client_name",
            DateTimeField("updated_at", label="Last event"),
            DateTimeField("last_used_at", label="Last used"),
            DateTimeField("last_refresh_at", label="Last refresh"),
            DateTimeField("access_expires_at", label="Access expires"),
            DateTimeField("refresh_expires_at", label="Refresh expires"),
            "last_event",
            "error_type",
            TextAreaField("error_message", label="Last error"),
            "client_id",
            "subject",
            TextAreaField("scopes_json", label="Scopes"),
            "access_jti",
            "refresh_jti",
            "previous_refresh_jti",
            DateTimeField("revoked_at", label="Revoked"),
            DateTimeField("created_at", label="Created"),
            "id",
        ),
    )
    fields_default_sort = (("updated_at", True),)
    searchable_fields = (
        "status",
        "login",
        "resource",
        "client_name",
        "client_id",
        "last_event",
        "error_type",
    )
    exclude_fields_from_list = (
        "error_message",
        "subject",
        "scopes_json",
        "access_jti",
        "refresh_jti",
        "previous_refresh_jti",
        "revoked_at",
        "created_at",
        "id",
    )

    def __init__(self, model: type[OAuthSessionRecord], service: OAuthSessionService) -> None:
        super().__init__(
            model,
            icon="fa fa-key",
            menu_label="OAuth Sessions",
            display_name="OAuth Session",
        )
        self.service = service
        self.page_size_options = [25, 50, 100]

    def can_create(self, _request: Request) -> bool:
        return False

    def can_edit(self, _request: Request) -> bool:
        return False


class ReverseView(CustomView):
    menu_label = "Reverse"
    icon = "fa fa-diagram-project"
    path = "/reverse"

    def __init__(self, reverse: ReverseAdminClient) -> None:
        super().__init__()
        self.reverse = reverse

    @route("")
    async def index(self, request: Request) -> Response:
        try:
            overview = await self.reverse.overview()
            error = ""
        except Exception as exc:
            overview = {"projects": [], "workers": [], "worker_count": 0, "count": 0}
            error = str(exc)

        projects = overview.get("projects")
        workers = overview.get("workers")
        project_items = projects if isinstance(projects, list) else []
        worker_items = workers if isinstance(workers, list) else []

        group_filter = request.query_params.get("group", "").strip()
        groups: dict[str, list[JsonObject]] = {}
        for raw in project_items:
            if not isinstance(raw, dict):
                continue
            item = raw
            group = str(item.get("group") or "Root")
            if group_filter and group != group_filter:
                continue
            groups.setdefault(group, []).append(item)

        active = sum(
            1
            for item in project_items
            if isinstance(item, dict) and item.get("session") == "active"
        )
        queued = sum(
            json_int(item.get("queued"), default=0)
            for item in worker_items
            if isinstance(item, dict)
        )
        running = sum(
            1
            for item in worker_items
            if isinstance(item, dict) and bool(item.get("running"))
        )
        enabled_workers = sum(
            1
            for item in worker_items
            if isinstance(item, dict) and bool(item.get("enabled", True))
        )
        all_groups = sorted(
            {
                str(item.get("group") or "Root")
                for item in project_items
                if isinstance(item, dict)
            },
            key=str.casefold,
        )

        return _view_templates(self).TemplateResponse(
            request=request,
            name="management_reverse.html",
            context={
                "title": "Reverse",
                "overview": overview,
                "projects": project_items,
                "project_groups": groups,
                "groups": all_groups,
                "group_filter": group_filter,
                "workers": worker_items,
                "active_sessions": active,
                "queued_total": queued,
                "running_workers": running,
                "enabled_workers": enabled_workers,
                "error": error,
            },
        )

    @route("/project/{project_id:path}")
    async def project_detail(self, request: Request) -> Response:
        project_id = request.path_params["project_id"]
        folder = request.query_params.get("folder", "/") or "/"
        error = ""
        coverage: JsonObject | None = None
        coverage_program = request.query_params.get("program", "").strip()
        coverage_mode = request.query_params.get("coverage", "").strip().casefold()
        try:
            session = await self.reverse.session_info(project_id)
        except Exception as exc:
            session = {"project_id": project_id, "session": "unknown"}
            error = str(exc)

        files: JsonObject = {}
        programs: list[JsonValue] = []
        folder_links: list[dict[str, str]] = []
        parent_folder: str | None = None
        if session.get("session") == "active" and not error:
            try:
                files, programs = await asyncio.gather(
                    self.reverse.project_files(project_id, folder),
                    self.reverse.open_programs(project_id),
                )
                if coverage_program and coverage_mode in {"quick", "full"}:
                    coverage = await self.reverse.coverage(
                        project_id,
                        coverage_program,
                        full=coverage_mode == "full",
                    )
            except Exception as exc:
                error = str(exc)

        raw_folders = files.get("folders")
        if isinstance(raw_folders, list):
            base = folder.rstrip("/")
            for raw_name in raw_folders:
                if not isinstance(raw_name, str) or not raw_name:
                    continue
                folder_links.append(
                    {
                        "name": raw_name,
                        "path": f"/{raw_name}" if not base else f"{base}/{raw_name}",
                    }
                )
        if folder != "/":
            parent_folder = posixpath.dirname(folder.rstrip("/")) or "/"

        return _view_templates(self).TemplateResponse(
            request=request,
            name="management_reverse_project.html",
            context={
                "title": "Reverse Project",
                "project_id": project_id,
                "folder": folder,
                "session": session,
                "files": files,
                "programs": programs,
                "folder_links": folder_links,
                "parent_folder": parent_folder,
                "coverage": coverage,
                "coverage_program": coverage_program,
                "coverage_mode": coverage_mode,
                "error": error,
            },
        )

    @route("/open/{project_id:path}", methods=["POST"])
    async def open_session(self, request: Request) -> Response:
        project_id = request.path_params["project_id"]
        try:
            await self.reverse.open_session(project_id)
        except Exception as exc:
            flash(request, f"Open session failed: {exc}", "error")
        else:
            flash(request, "Project session opened", "success")
        return RedirectResponse("/admin/reverse", status_code=303)

    @route("/release/{project_id:path}", methods=["POST"])
    async def release_session(self, request: Request) -> Response:
        project_id = request.path_params["project_id"]
        try:
            await self.reverse.release_session(project_id)
        except Exception as exc:
            flash(request, f"Release session failed: {exc}", "error")
        else:
            flash(request, "Project session released", "success")
        return RedirectResponse("/admin/reverse", status_code=303)


    @route("/create", methods=["POST"])
    async def create_project(self, request: Request) -> Response:
        form = await request.form()
        name = str(form.get("name", "")).strip()
        parent_dir = str(form.get("parent_dir", "")).strip()
        if not name:
            flash(request, "Project name is required", "error")
            return RedirectResponse("/admin/reverse", status_code=303)
        try:
            result = await self.reverse.create_project(name, parent_dir)
        except Exception as exc:
            flash(request, f"Create project failed: {exc}", "error")
        else:
            project_id = str(result.get("project_id") or "")
            flash(request, f"Created project {name}", "success")
            if project_id:
                return RedirectResponse(
                    f"/admin/reverse/project/{project_id}",
                    status_code=303,
                )
        return RedirectResponse("/admin/reverse", status_code=303)

    @route("/delete/{project_id:path}", methods=["POST"])
    async def delete_project(self, request: Request) -> Response:
        project_id = request.path_params["project_id"]
        try:
            result = await self.reverse.delete_project(project_id)
        except Exception as exc:
            flash(request, f"Delete project failed: {exc}", "error")
        else:
            name = str(result.get("name") or project_id)
            flash(request, f"Deleted project {name}", "success")
        return RedirectResponse("/admin/reverse", status_code=303)

    @route("/worker/{worker_index:path}/{action}", methods=["POST"])
    async def worker_control(self, request: Request) -> Response:
        try:
            worker_index = int(request.path_params["worker_index"])
        except ValueError:
            flash(request, "Invalid worker index", "error")
            return RedirectResponse("/admin/reverse", status_code=303)

        action = request.path_params["action"].casefold()
        if action not in {"enable", "disable"}:
            flash(request, "Invalid worker action", "error")
            return RedirectResponse("/admin/reverse", status_code=303)

        try:
            await self.reverse.set_worker_enabled(
                worker_index,
                enabled=action == "enable",
            )
        except Exception as exc:
            flash(request, f"Worker control failed: {exc}", "error")
        else:
            flash(
                request,
                f"Worker #{worker_index} {action}d",
                "success",
            )
        return RedirectResponse("/admin/reverse", status_code=303)


class TerminalView(CustomView):
    menu_label = "Terminal"
    icon = "fa fa-terminal"
    path = "/terminal"

    def __init__(self, terminal: TerminalAdminClient) -> None:
        super().__init__()
        self.terminal = terminal

    @route("")
    async def index(self, request: Request) -> Response:
        try:
            overview = await self.terminal.overview()
            error = ""
        except Exception as exc:
            overview = {"status": {}, "workspaces": [], "jobs": []}
            error = str(exc)
        status = overview.get("status")
        workspaces = overview.get("workspaces")
        jobs = overview.get("jobs")
        status_obj = status if isinstance(status, dict) else {}
        workspace_items = workspaces if isinstance(workspaces, list) else []
        job_items = jobs if isinstance(jobs, list) else []
        running = sum(
            1 for item in job_items
            if isinstance(item, dict) and item.get("state") in {"running", "cancelling"}
        )
        failed = sum(
            1 for item in job_items
            if isinstance(item, dict) and item.get("state") in {"failed", "interrupted"}
        )
        return _view_templates(self).TemplateResponse(
            request=request,
            name="management_terminal.html",
            context={
                "title": "Terminal",
                "status": status_obj,
                "workspaces": workspace_items,
                "jobs": job_items,
                "running_jobs": running,
                "failed_jobs": failed,
                "error": error,
            },
        )

    @route("/job/{job_id:path}")
    async def job_detail(self, request: Request) -> Response:
        job_id = request.path_params["job_id"]
        try:
            job, tail = await asyncio.gather(
                self.terminal.job_status(job_id),
                self.terminal.job_tail(job_id),
            )
            error = ""
        except Exception as exc:
            job = {"job_id": job_id}
            tail = {}
            error = str(exc)
        return _view_templates(self).TemplateResponse(
            request=request,
            name="management_terminal_job.html",
            context={
                "title": "Terminal Job",
                "job": job,
                "tail": tail,
                "error": error,
            },
        )

    @route("/job/{job_id:path}/cancel", methods=["POST"])
    async def cancel_job(self, request: Request) -> Response:
        job_id = request.path_params["job_id"]
        try:
            await self.terminal.cancel_job(job_id)
        except Exception as exc:
            flash(request, f"Cancel job failed: {exc}", "error")
        else:
            flash(request, "Job cancelled", "success")
        return RedirectResponse("/admin/terminal", status_code=303)

    @route("/job/{job_id:path}/delete", methods=["POST"])
    async def delete_job(self, request: Request) -> Response:
        job_id = request.path_params["job_id"]
        try:
            await self.terminal.delete_job(job_id)
        except Exception as exc:
            flash(request, f"Delete job failed: {exc}", "error")
        else:
            flash(request, "Job log deleted", "success")
        return RedirectResponse("/admin/terminal", status_code=303)

    @route("/cleanup-jobs", methods=["POST"])
    async def cleanup_jobs(self, request: Request) -> Response:
        form = await request.form()
        try:
            older_than_hours = int(str(form.get("older_than_hours", "168")))
            result = await self.terminal.cleanup_jobs(
                older_than_hours=older_than_hours,
                dry_run=False,
            )
        except Exception as exc:
            flash(request, f"Job cleanup failed: {exc}", "error")
        else:
            flash(request, f"Deleted {result.get('count', 0)} retained jobs", "success")
        return RedirectResponse("/admin/terminal", status_code=303)

    @route("/workspace/{workspace_id:path}/delete", methods=["POST"])
    async def delete_workspace(self, request: Request) -> Response:
        workspace_id = request.path_params["workspace_id"]
        try:
            await self.terminal.delete_workspace(workspace_id)
        except Exception as exc:
            flash(request, f"Delete workspace failed: {exc}", "error")
        else:
            flash(request, f"Deleted workspace {workspace_id}", "success")
        return RedirectResponse("/admin/terminal", status_code=303)


class SettingsView(CustomView):
    menu_label = "Settings"
    icon = "fa fa-sliders"
    path = "/settings"

    def __init__(
        self,
        config: ManagementConfigService,
        audit: InvocationAuditService,
        reverse: ReverseAdminClient,
    ) -> None:
        super().__init__()
        self.config = config
        self.audit = audit
        self.reverse = reverse

    @staticmethod
    def _form_config(form: FormData) -> ManagementConfig:
        return ManagementConfig(
            logging_enabled="logging_enabled" in form,
            logging_capture_payloads="logging_capture_payloads" in form,
            logging_retention_days=int(str(form.get("logging_retention_days", "30"))),
            logging_max_records=int(str(form.get("logging_max_records", "10000"))),
            maintenance_interval_minutes=int(
                str(form.get("maintenance_interval_minutes", "60"))
            ),
        )

    @route("", methods=["GET", "POST"])
    async def index(self, request: Request) -> Response:
        if request.method == "POST":
            form = await request.form()
            try:
                config = self._form_config(form)
                reverse_idle_timeout = float(
                    str(form.get("reverse_idle_timeout_seconds", "900"))
                )
                if not 0 <= reverse_idle_timeout <= 86_400:
                    raise ValueError(
                        "Reverse idle timeout must be between 0 and 86400 seconds"
                    )
                await self.reverse.set_idle_timeout(reverse_idle_timeout)
                await asyncio.to_thread(self.config.update, config)
            except (TypeError, ValueError, RuntimeError) as exc:
                flash(request, f"Invalid settings: {exc}", "error")
            else:
                flash(request, "Settings saved", "success")
                return RedirectResponse("/admin/settings", status_code=303)

        config = await asyncio.to_thread(self.config.get)
        try:
            reverse_settings = await self.reverse.session_settings()
            reverse_error = ""
        except Exception as exc:
            reverse_settings = {
                "idle_timeout_seconds": 900.0,
                "auto_release_enabled": True,
                "source": "unavailable",
            }
            reverse_error = str(exc)

        return _view_templates(self).TemplateResponse(
            request=request,
            name="management_settings.html",
            context={
                "title": "Settings",
                "config": config,
                "reverse_settings": reverse_settings,
                "reverse_error": reverse_error,
            },
        )

    @route("/cleanup-logs", methods=["POST"])
    async def cleanup_logs(self, request: Request) -> Response:
        removed = await asyncio.to_thread(self.audit.cleanup)
        flash(request, f"Removed {removed} expired MCP call records", "success")
        return RedirectResponse("/admin/settings", status_code=303)


class FilesView(CustomView):
    menu_label = "Files"
    icon = "fa fa-folder-open"
    path = "/files"

    def __init__(self, files: FileAdminStore) -> None:
        super().__init__()
        self.files = files

    @route("")
    async def index(self, request: Request) -> Response:
        current = request.query_params.get("path", "").strip().strip("/")
        try:
            listing, stats = await asyncio.gather(
                asyncio.to_thread(self.files.list, current, limit=500),
                asyncio.to_thread(self.files.stats),
            )
            error = ""
        except Exception as exc:
            listing = {
                "path": current or "/",
                "entries": [],
                "count": 0,
                "total": 0,
                "truncated": False,
            }
            stats = {}
            error = str(exc)
        parent = posixpath.dirname(current) if current else ""
        return _view_templates(self).TemplateResponse(
            request=request,
            name="management_files.html",
            context={
                "title": "Files",
                "listing": listing,
                "stats": stats,
                "current_path": current,
                "parent_path": parent,
                "error": error,
            },
        )

    @route("/upload", methods=["POST"])
    async def upload(self, request: Request) -> Response:
        form = await request.form()
        upload = form.get("file")
        current = str(form.get("path", "")).strip().strip("/")
        overwrite = str(form.get("overwrite", "")).lower() in {
            "1", "true", "on", "yes"
        }
        if not isinstance(upload, UploadFile):
            flash(request, "Choose a file to upload", "error")
        else:
            name = Path(upload.filename or "upload.bin").name
            destination = posixpath.join(current, name) if current else name
            try:
                await asyncio.to_thread(
                    self.files.upload,
                    upload.file,
                    destination=destination,
                    overwrite=overwrite,
                )
            except Exception as exc:
                flash(request, f"Upload failed: {exc}", "error")
            else:
                flash(request, f"Uploaded {destination}", "success")
        return RedirectResponse(
            f"/admin/files?{urllib.parse.urlencode({'path': current})}",
            status_code=303,
        )

    @route("/mkdir", methods=["POST"])
    async def mkdir(self, request: Request) -> Response:
        form = await request.form()
        current = str(form.get("path", "")).strip().strip("/")
        name = str(form.get("name", "")).strip().strip("/")
        if not name or "/" in name or "\\" in name:
            flash(request, "A single directory name is required", "error")
        else:
            destination = posixpath.join(current, name) if current else name
            try:
                await asyncio.to_thread(self.files.mkdir, destination)
            except Exception as exc:
                flash(request, f"Create directory failed: {exc}", "error")
            else:
                flash(request, f"Created {destination}", "success")
        return RedirectResponse(
            f"/admin/files?{urllib.parse.urlencode({'path': current})}",
            status_code=303,
        )

    @route("/download")
    async def download(self, request: Request) -> Response:
        path = request.query_params.get("path", "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="file path is required")
        try:
            info = await asyncio.to_thread(self.files.info, path)
            file_path = await asyncio.to_thread(self.files.path_for, path)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if info.get("type") != "file":
            raise HTTPException(status_code=400, detail="path is not a file")
        return FileResponse(
            file_path,
            filename=str(info.get("name") or file_path.name),
            media_type=str(info.get("mime_type") or "application/octet-stream"),
        )

    @route("/delete", methods=["POST"])
    async def delete(self, request: Request) -> Response:
        form = await request.form()
        current = str(form.get("current_path", "")).strip().strip("/")
        path = str(form.get("path", "")).strip()
        recursive = str(form.get("recursive", "")).lower() in {
            "1", "true", "on", "yes"
        }
        try:
            await asyncio.to_thread(
                self.files.delete,
                path,
                recursive=recursive,
            )
        except Exception as exc:
            flash(request, f"Delete failed: {exc}", "error")
        else:
            flash(request, f"Deleted {path}", "success")
        return RedirectResponse(
            f"/admin/files?{urllib.parse.urlencode({'path': current})}",
            status_code=303,
        )


def _view_templates(view: CustomView) -> Jinja2Templates:
    if view.templates is None:
        raise RuntimeError("admin templates are not initialized")
    return view.templates


def _dashboard(
    engine: Engine,
    files: FileAdminStore,
    reverse: ReverseAdminClient,
) -> CustomView:
    async def count(
        model: type[object],
        *_filters: ColumnElement[bool],
    ) -> int:
        statement = select(func.count()).select_from(model)
        for criterion in _filters:
            statement = statement.where(criterion)
        return await asyncio.to_thread(_scalar, engine, statement)

    async def count_accounts(_request: Request) -> int:
        github, gitlab = await asyncio.gather(
            count(GitHubAccountRecord, GitHubAccountRecord.enabled.is_(True)),
            count(GitLabAccountRecord, GitLabAccountRecord.enabled.is_(True)),
        )
        return github + gitlab

    async def count_github(_request: Request) -> int:
        return await count(GitHubAccountRecord, GitHubAccountRecord.enabled.is_(True))

    async def count_gitlab(_request: Request) -> int:
        return await count(GitLabAccountRecord, GitLabAccountRecord.enabled.is_(True))

    async def count_oauth_sessions(_request: Request) -> int:
        return await count(OAuthSessionRecord, OAuthSessionRecord.status == "active")

    async def count_calls(_request: Request) -> int:
        return await count(InvocationRecord)

    async def count_errors(_request: Request) -> int:
        return await count(InvocationRecord, InvocationRecord.status == "error")

    async def average_duration(_request: Request) -> int:
        return await asyncio.to_thread(
            _scalar,
            engine,
            select(func.avg(InvocationRecord.duration_ms)),
        )

    async def stored_files(_request: Request) -> int:
        stats = await asyncio.to_thread(files.stats)
        return json_int(stats.get("files"), field="files")

    async def storage_used(_request: Request) -> str:
        stats = await asyncio.to_thread(files.stats)
        return json_str(stats.get("size_display"), default="0 B", field="size_display")

    async def reverse_overview(request: Request) -> JsonObject:
        task = cast(
            asyncio.Task[JsonObject] | None,
            getattr(request.state, "_reverse_overview_task", None),
        )
        if task is None:
            task = asyncio.create_task(reverse.overview())
            request.state._reverse_overview_task = task
        try:
            return await task
        except Exception:
            return {"projects": [], "workers": []}

    async def reverse_projects(request: Request) -> int:
        overview = await reverse_overview(request)
        projects = overview.get("projects")
        return len(projects) if isinstance(projects, list) else 0

    async def reverse_sessions(request: Request) -> int:
        overview = await reverse_overview(request)
        projects = overview.get("projects")
        if not isinstance(projects, list):
            return 0
        return sum(
            1
            for item in projects
            if isinstance(item, dict) and item.get("session") == "active"
        )

    async def reverse_workers(request: Request) -> int:
        overview = await reverse_overview(request)
        workers = overview.get("workers")
        if not isinstance(workers, list):
            return 0
        return sum(
            1
            for item in workers
            if isinstance(item, dict) and bool(item.get("enabled", True))
        )

    async def reverse_queue(request: Request) -> int:
        overview = await reverse_overview(request)
        workers = overview.get("workers")
        if not isinstance(workers, list):
            return 0
        return sum(
            json_int(item.get("queued"), default=0)
            for item in workers
            if isinstance(item, dict)
        )

    async def error_rate(_request: Request) -> float:
        calls, errors = await asyncio.gather(count_calls(_request), count_errors(_request))
        return round((errors / calls) * 100, 1) if calls else 0.0

    return CustomView(
        menu_label="Dashboard",
        icon="fa fa-home",
        widget=CardRowWidget(
            children=[
                Col(
                    StatWidget(title="Active accounts", value_callback=count_accounts),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="GitHub accounts", value_callback=count_github),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="GitLab accounts", value_callback=count_gitlab),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Active OAuth sessions", value_callback=count_oauth_sessions),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="MCP calls", value_callback=count_calls),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Errors", value_callback=count_errors),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Error rate (%)", value_callback=error_rate),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Average duration (ms)", value_callback=average_duration),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Stored files", value_callback=stored_files),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Storage used", value_callback=storage_used),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Reverse projects", value_callback=reverse_projects),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Reverse sessions", value_callback=reverse_sessions),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Reverse workers", value_callback=reverse_workers),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Reverse queued", value_callback=reverse_queue),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
            ]
        ),
    )


def _scalar(engine: Engine, statement: Executable) -> int:
    with engine.connect() as connection:
        value = connection.scalar(statement)
    if value is None:
        return 0
    return round(float(value))


def build_admin(
    engine: Engine,
    settings: ManagementSettings,
    cipher: FernetCredentialCipher,
    accounts: AccountService,
    audit: InvocationAuditService,
    oauth_sessions: OAuthSessionService,
    config: ManagementConfigService,
    files: FileAdminStore,
) -> Admin:
    reverse = ReverseAdminClient()
    terminal = TerminalAdminClient()
    admin = Admin(
        engine,
        title="MCP Management",
        base_url="/admin",
        auth_provider=ManagementAuthProvider(settings),
        secret_key=settings.session_secret,
        index_view=_dashboard(engine, files, reverse),
        templates_dir=str(Path(__file__).with_name("templates")),
        plugins=[ManagementUiPlugin()],
    )
    admin.add_view(FilesView(files))
    admin.add_view(
        GitHubAccountView(
            GitHubAccountRecord,
            cipher,
            accounts,
            icon="fa-brands fa-github",
            menu_label="GitHub Accounts",
        )
    )
    admin.add_view(
        GitLabAccountView(
            GitLabAccountRecord,
            cipher,
            accounts,
            icon="fa-brands fa-gitlab",
            menu_label="GitLab Accounts",
        )
    )
    admin.add_view(ReverseView(reverse))
    admin.add_view(TerminalView(terminal))
    admin.add_view(OAuthSessionView(OAuthSessionRecord, oauth_sessions))
    admin.add_view(InvocationView(InvocationRecord, audit))
    admin.add_view(SettingsView(config, audit, reverse))
    return admin
