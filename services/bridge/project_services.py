"""Internal Project Gateway application routing. NEVER a public FastMCP mount.

Only explicit non-destructive tool names are routed. Operation schemas are
private types, not promised public REST or MCP DTOs. A trusted ProjectInvocation
from a service-authenticated caller is reauthorized by the owning domain on
EVERY call; ProjectPermit alone is not network authentication. Domain packages
are TYPE_ONLY imports so the existing Gateway Docker stage stays import-safe.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from common.models import JsonObject
from modules.project_runtime import ProjectAction, ProjectRuntimeAuthority
from modules.project_runtime.integrations import IntegrationProvider
from modules.project_runtime.resource_query import ResourceFilter

from .project_dispatch import (
    _PRIVATE_TOOL_ACTIONS,
    AuthorizedToolForward,
    ProjectGatewayDispatchUnavailable,
)

if TYPE_CHECKING:
    from modules.files.project_files import ProjectFilesService
    from modules.project_runtime.integrations import (
        ProjectIntegrationRef,
        ProjectIntegrationSelector,
    )
    from modules.project_runtime.variables import ProjectVariableRef, ProjectVariableSelector


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Path(_Model):
    path: str = Field(min_length=1, max_length=4096)


class _FileList(_Model):
    path: str = Field(default="", max_length=4096)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)


class _Read(_Path):
    max_bytes: int = Field(default=65536, ge=1, le=262144)


class _FileUpload(_Model):
    """Only a small private MCP payload; larger transfers need a real API."""

    destination: str = Field(min_length=1, max_length=4096)
    operation_uuid: UUID
    size_bytes: int = Field(ge=0, le=262144)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_base64: str = Field(max_length=349528)

    @field_validator("operation_uuid", mode="before")
    @classmethod
    def canonical_json_uuidv4(cls, value: object) -> UUID:
        # JSON/MCP sends UUIDs as strings, even under strict Pydantic models.
        # Accept ONLY canonical, lowercase UUIDv4; never silently coerce ints.
        if isinstance(value, UUID):
            parsed = value
        elif isinstance(value, str) and len(value) == 36:
            try:
                parsed = UUID(value)
            except ValueError as exc:
                raise ValueError("operation_uuid must be canonical UUIDv4") from exc
            if str(parsed) != value:
                raise ValueError("operation_uuid must be canonical UUIDv4")
        else:
            raise ValueError("operation_uuid must be canonical UUIDv4")
        if parsed.version != 4:
            raise ValueError("operation_uuid must be UUIDv4")
        return parsed


class _FileWriteStatus(_Model):
    operation_uuid: UUID

    @field_validator("operation_uuid", mode="before")
    @classmethod
    def canonical_uuid(cls, value: object) -> UUID:
        return _FileUpload.canonical_json_uuidv4(value)


class _ResourceList(_Model):
    scope: ResourceFilter = "all"
    owner_id: UUID | None = None

    @field_validator("owner_id", mode="before")
    @classmethod
    def canonical_owner_id(cls, value: object) -> UUID | None:
        if value is None:
            return None
        return _FileUpload.canonical_json_uuidv4(value)


class _InfrastructureList(_ResourceList):
    provider: Literal["coolify", "signoz"]


# These are source-only in-process selectors; they are deliberately not
# registered via `@mcp.tool` and are NOT dynamically discoverable in FastMCP.


class PrivateProjectToolClassifier:
    """Precise mapping; never interprets caller-selected action/grant."""

    async def classify(self, backend: str, tool: str) -> ProjectAction | None:
        return _PRIVATE_TOOL_ACTIONS.get((backend, tool))


class PrivateProjectModuleForwarder:
    """Private Project Files read/small upload and metadata-only resources.

    Upload requires accepted A5 SQL quota reserve+dispatch+finalize and is
    NOT a public route. All privileged Terminal/Provider/Ghidra effects still
    require explicit Backend/OS contracts and independent C1-B2/C2 approval.
    """

    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        *,
        files: ProjectFilesService | None = None,
        integrations: ProjectIntegrationSelector | None = None,
        variables: ProjectVariableSelector | None = None,
    ) -> None:
        self.authority = authority
        self.files = files
        self.integrations = integrations
        self.variables = variables

    @staticmethod
    def _args[T: BaseModel](model: type[T], data: JsonObject) -> T:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise ProjectGatewayDispatchUnavailable("PROJECT_ARGUMENTS_INVALID") from exc

    @staticmethod
    def _integration_item(ref: ProjectIntegrationRef) -> JsonObject:
        return {
            "resource_id": str(ref.resource_id),
            "name": ref.name,
            "provider": ref.provider,
            "auth_type": ref.credential_type,
            "owner_scope": ref.scope.owner_scope,
            "owner_id": str(ref.scope.owner_id),
            "inherited": ref.scope.inherited,
            "resource_version": ref.scope.resource_revision,
        }

    @staticmethod
    def _variable_item(ref: ProjectVariableRef) -> JsonObject:
        # No plaintext variable, even for configuration variables. The trusted
        # Backend may later expose an explicitly allowed public-value DTO.
        return {
            "resource_id": str(ref.resource_id),
            "name": ref.name,
            "kind": ref.kind,
            "owner_scope": ref.scope.owner_scope,
            "owner_id": str(ref.scope.owner_id),
            "inherited": ref.scope.inherited,
            "resource_version": ref.scope.resource_revision,
            "masked": True,
        }

    async def normalize(self, *, backend: str, tool: str, arguments: JsonObject) -> JsonObject:
        """Validate the concrete tool schema BEFORE creating A5 proof.

        The result is JSON-canonical (UUID strings, defaults explicit) so the
        signed request fingerprint binds the actual operation and payload,
        not an arbitrary caller-supplied dictionary or provider alias.
        """
        model: type[_Model]
        if backend == "files":
            if tool == "list":
                model = _FileList
            elif tool in {"info", "sha256"}:
                model = _Path
            elif tool == "read_base64":
                model = _Read
            elif tool == "upload_base64":
                model = _FileUpload
            elif tool == "write_status":
                model = _FileWriteStatus
            else:
                raise ProjectGatewayDispatchUnavailable("PROJECT_TOOL_NOT_AUTHORIZED")
        elif backend in {"github", "gitlab", "variables"} and tool in {"connections", "metadata"}:
            model = _ResourceList
        elif backend == "observability" and tool == "connections":
            model = _InfrastructureList
        else:
            raise ProjectGatewayDispatchUnavailable("PROJECT_TOOL_NOT_AUTHORIZED")
        prepared = self._args(model, arguments)
        return cast(JsonObject, prepared.model_dump(mode="json"))

    async def forward(self, request: AuthorizedToolForward) -> JsonObject:
        backend, tool = request.backend, request.tool
        action = _PRIVATE_TOOL_ACTIONS.get((backend, tool))
        if action is None or action != request.permit.action:
            raise ProjectGatewayDispatchUnavailable("PROJECT_TOOL_NOT_AUTHORIZED")
        # Refresh current active User+Project/Team+AgentSession+service grant
        # before touching sensitive Project Files or effective resources.
        current = await self.authority.require(request.invocation, action)
        if (
            current.project_id != request.permit.project_id
            or current.actor_id != request.permit.actor_id
            or current.session_uuid != request.permit.session_uuid
            or current.project_access_revision != request.permit.project_access_revision
            or current.project_owner_id != request.permit.project_owner_id
            or current.project_owner_scope != request.permit.project_owner_scope
        ):
            raise ProjectGatewayDispatchUnavailable("PROJECT_ACCESS_STALE")

        if backend == "files":
            if self.files is None:
                raise ProjectGatewayDispatchUnavailable("PROJECT_FILES_NOT_CONFIGURED")
            if tool == "list":
                list_args = self._args(_FileList, request.arguments)
                page = await self.files.list(
                    request.invocation,
                    list_args.path,
                    offset=list_args.offset,
                    limit=list_args.limit,
                )
                return {
                    "entries": [
                        {
                            "path": entry.path,
                            "kind": entry.kind,
                            "size_bytes": entry.size_bytes,
                            "modified_at_ns": entry.modified_at_ns,
                        }
                        for entry in page.entries
                    ],
                    "total": page.total,
                    "offset": page.offset,
                    "limit": page.limit,
                }
            if tool == "info":
                path_args = self._args(_Path, request.arguments)
                info = await self.files.info(request.invocation, path_args.path)
                return {
                    "path": info.path,
                    "kind": info.kind,
                    "size_bytes": info.size_bytes,
                    "modified_at_ns": info.modified_at_ns,
                }
            if tool == "sha256":
                path_args = self._args(_Path, request.arguments)
                digest = await self.files.sha256(request.invocation, path_args.path)
                return {"path": path_args.path, "sha256": digest}
            if tool == "write_status":
                args_status = self._args(_FileWriteStatus, request.arguments)
                if (
                    args_status.operation_uuid != request.request_uuid
                    or self.files.a5_quota is None
                ):
                    raise ProjectGatewayDispatchUnavailable("PROJECT_A5_WRITE_STATUS_UNAVAILABLE")
                inspected = await self.files.a5_quota.inspect(
                    request.invocation,
                    permit=current,
                    operation_uuid=request.request_uuid,
                )
                if inspected is None:
                    # An absent ledger row is NOT proof an unknown write
                    # never reached disk. Never grant speculative retry.
                    return {
                        "operation_uuid": str(request.request_uuid),
                        "found": False,
                        "retry_allowed": False,
                        "outcome": "unverified",
                    }
                return {
                    "operation_uuid": str(request.request_uuid),
                    "found": True,
                    "retry_allowed": False,
                    "outcome": inspected.state,
                    "ledger_revision": inspected.revision,
                    "planned_bytes": inspected.planned_bytes,
                    "expires_at": inspected.expires_at.isoformat(),
                    "disk_observation_required": inspected.state in {"dispatched", "unknown"},
                }
            if tool == "upload_base64":
                args_upload = self._args(_FileUpload, request.arguments)
                # A generic R6 quota adapter is not the accepted A5 dispatched
                # write ledger. Refuse that fallback for this first Project
                # Files vertical even in a private Gateway composition.
                if self.files.a5_quota is None:
                    raise ProjectGatewayDispatchUnavailable("PROJECT_A5_FILES_QUOTA_REQUIRED")
                if (
                    args_upload.operation_uuid.version != 4
                    or args_upload.operation_uuid != request.request_uuid
                ):
                    raise ProjectGatewayDispatchUnavailable("PROJECT_REQUEST_UUID_MISMATCH")
                try:
                    body = base64.b64decode(args_upload.content_base64, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise ProjectGatewayDispatchUnavailable(
                        "PROJECT_UPLOAD_ENCODING_INVALID"
                    ) from exc
                if (
                    len(body) != args_upload.size_bytes
                    or hashlib.sha256(body).hexdigest() != args_upload.sha256
                ):
                    raise ProjectGatewayDispatchUnavailable("PROJECT_UPLOAD_CHECKSUM_INVALID")
                try:
                    saved = await self.files.write(
                        request.invocation,
                        args_upload.destination,
                        body,
                        operation_uuid=request.request_uuid,
                    )
                except Exception as exc:
                    # A5 reserve/dispatch/rename/finalize can commit before
                    # its response is lost. Never leak exception internals or
                    # tell an agent that a second write is safe.
                    raise ProjectGatewayDispatchUnavailable(
                        "PROJECT_FILE_OUTCOME_UNKNOWN",
                        operation_uuid=request.request_uuid,
                    ) from exc
                if saved.kind != "file" or saved.size_bytes != len(body):
                    raise ProjectGatewayDispatchUnavailable("PROJECT_FILE_COMMIT_UNCERTAIN")
                return {
                    "operation_uuid": str(request.request_uuid),
                    "path": saved.path,
                    "kind": "file",
                    "size_bytes": saved.size_bytes,
                    "sha256": args_upload.sha256,
                    "status": "committed",
                }
            if tool == "read_base64":
                read_args = self._args(_Read, request.arguments)
                contents = await self.files.read(
                    request.invocation, read_args.path, max_bytes=read_args.max_bytes
                )
                return {
                    "path": read_args.path,
                    "encoding": "base64",
                    "data": base64.b64encode(contents).decode("ascii"),
                    "size_bytes": len(contents),
                    "sha256": hashlib.sha256(contents).hexdigest(),
                }

        if backend in {"github", "gitlab", "observability"}:
            if self.integrations is None:
                raise ProjectGatewayDispatchUnavailable("PROJECT_INTEGRATIONS_NOT_CONFIGURED")
            selection: _ResourceList
            if backend == "observability":
                selection = self._args(_InfrastructureList, request.arguments)
                provider: IntegrationProvider = selection.provider
            else:
                selection = self._args(_ResourceList, request.arguments)
                provider = cast(IntegrationProvider, backend)
            connections = await self.integrations.list(
                request.invocation,
                provider=provider,
                scope=selection.scope,
                owner_id=selection.owner_id,
            )
            return {"resources": [self._integration_item(ref) for ref in connections]}

        if backend == "variables" and tool == "metadata":
            if self.variables is None:
                raise ProjectGatewayDispatchUnavailable("PROJECT_VARIABLES_NOT_CONFIGURED")
            args_v = self._args(_ResourceList, request.arguments)
            variables = await self.variables.list_metadata(
                request.invocation, scope=args_v.scope, owner_id=args_v.owner_id
            )
            return {"resources": [self._variable_item(ref) for ref in variables]}

        raise ProjectGatewayDispatchUnavailable("PROJECT_TOOL_NOT_AUTHORIZED")
