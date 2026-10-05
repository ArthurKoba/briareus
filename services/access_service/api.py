from __future__ import annotations

import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, Response

from common.access_contracts import (
    AdminResolveRequest,
    AdminSessionOwnerRequest,
    AdminSessionUpdate,
    ExtensionRequest,
    FullAccessRequest,
    SessionOpenRequest,
    SessionUpdateRequest,
    SessionValidateRequest,
    SurfaceControlBatchUpdate,
    SurfaceControlUpdate,
)
from common.mcp_surfaces import MCP_SURFACE_IDS
from common.settings import AccessServiceSettings

from .service import AccessService


def build_access_app(
    service: AccessService,
    settings: AccessServiceSettings,
) -> FastAPI:
    app = FastAPI(title="Access Service", docs_url=None, redoc_url=None)

    def _require(expected: str, authorization: str | None) -> None:
        candidate = f"Bearer {expected}"
        if not authorization or not hmac.compare_digest(authorization, candidate):
            raise HTTPException(status_code=401, detail="unauthorized")

    async def require_gateway(
        authorization: str | None = Header(default=None),
    ) -> None:
        _require(settings.gateway_service_token, authorization)

    async def require_admin(
        authorization: str | None = Header(default=None),
    ) -> None:
        _require(settings.admin_service_token, authorization)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/session/open", dependencies=[Depends(require_gateway)])
    async def open_session(request: SessionOpenRequest) -> dict[str, object]:
        try:
            session = await service.open_session(request)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return session.model_dump(mode="json")

    @app.post("/v1/session/validate", dependencies=[Depends(require_gateway)])
    async def validate_session(request: SessionValidateRequest) -> dict[str, object]:
        return (await service.validate(request)).model_dump(mode="json")

    @app.post("/v1/session/status", dependencies=[Depends(require_gateway)])
    async def status(request: SessionValidateRequest) -> dict[str, object]:
        session = await service.status(
            context=request,
            surface_id=request.surface_id,
            uid=request.session_uid,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="session_not_found")
        return session.model_dump(mode="json")

    @app.post("/v1/session/update", dependencies=[Depends(require_gateway)])
    async def update_session(request: SessionUpdateRequest) -> dict[str, object]:
        try:
            session = await service.update_session(request)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return session.model_dump(mode="json")

    @app.post("/v1/session/request-full-access", dependencies=[Depends(require_gateway)])
    async def request_full_access(request: FullAccessRequest) -> dict[str, object]:
        try:
            pending = await service.request_full_access(request)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return pending.model_dump(mode="json")

    @app.post("/v1/session/request-extension", dependencies=[Depends(require_gateway)])
    async def request_extension(request: ExtensionRequest) -> dict[str, object]:
        try:
            pending = await service.request_extension(request)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return pending.model_dump(mode="json")

    @app.post("/v1/session/close", dependencies=[Depends(require_gateway)])
    async def close_session(request: SessionValidateRequest) -> dict[str, object]:
        try:
            session = await service.close_session(
                context=request,
                surface_id=request.surface_id,
                uid=request.session_uid,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return session.model_dump(mode="json")

    @app.post("/v1/session/reissue", dependencies=[Depends(require_gateway)])
    async def reissue_session(request: SessionUpdateRequest) -> dict[str, object]:
        try:
            session = await service.reissue_session(
                context=request,
                surface_id=request.surface_id,
                old_uid=request.session_uid,
                label=request.label,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return session.model_dump(mode="json")

    @app.get(
        "/v1/admin/users/{user_id}/sessions",
        dependencies=[Depends(require_admin)],
    )
    async def list_sessions(user_id: str) -> dict[str, object]:
        sessions = await service.repository.list_sessions(user_id)
        return {"sessions": [item.model_dump(mode="json") for item in sessions]}

    @app.get(
        "/v1/admin/users/{user_id}/requests",
        dependencies=[Depends(require_admin)],
    )
    async def list_requests(user_id: str) -> dict[str, object]:
        requests = await service.repository.list_pending_requests(user_id)
        return {"requests": [item.model_dump(mode="json") for item in requests]}

    @app.post(
        "/v1/admin/requests/{request_id}/resolve",
        dependencies=[Depends(require_admin)],
    )
    async def resolve_request(
        request_id: str,
        request: AdminResolveRequest,
    ) -> dict[str, object]:
        try:
            resolved, session = await service.resolve_request(request_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "request": resolved.model_dump(mode="json"),
            "session": session.model_dump(mode="json"),
        }

    @app.patch(
        "/v1/admin/sessions/{session_id}",
        dependencies=[Depends(require_admin)],
    )
    async def admin_update_session(
        session_id: str, request: AdminSessionUpdate
    ) -> dict[str, object]:
        try:
            updated = await service.admin_update(session_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return updated.model_dump(mode="json")

    @app.post(
        "/v1/admin/sessions/{session_id}/revoke",
        status_code=204,
        dependencies=[Depends(require_admin)],
    )
    async def admin_revoke(
        session_id: str, request: AdminSessionOwnerRequest
    ) -> Response:
        try:
            await service.admin_revoke(
                session_id, admin_user_id=request.admin_user_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(status_code=204)

    @app.get(
        "/v1/admin/users/{user_id}/controls",
        dependencies=[Depends(require_admin)],
    )
    async def list_controls(user_id: str) -> dict[str, object]:
        controls: list[dict[str, object]] = []
        for name, member in MCP_SURFACE_IDS.items():
            controls.append(
                {
                    "surface": name,
                    "surface_id": int(member),
                    "mode": await service.get_mode(user_id, int(member)),
                }
            )
        return {"controls": controls}

    @app.put("/v1/admin/controls/batch", dependencies=[Depends(require_admin)])
    async def set_controls_batch(
        request: SurfaceControlBatchUpdate,
    ) -> dict[str, object]:
        resolved = await service.set_modes_batch(
            [(item.user_id, item.surface_id, item.mode) for item in request.items]
        )
        return {
            "controls": [
                {"user_id": user_id, "surface_id": surface_id, "mode": mode}
                for user_id, surface_id, mode in resolved
            ]
        }

    @app.put("/v1/admin/control", dependencies=[Depends(require_admin)])
    async def set_control(request: SurfaceControlUpdate) -> dict[str, object]:
        mode = await service.set_mode(
            user_id=request.user_id,
            surface_id=request.surface_id,
            mode=request.mode,
        )
        return {
            "user_id": request.user_id,
            "surface_id": request.surface_id,
            "mode": mode,
        }

    return app
