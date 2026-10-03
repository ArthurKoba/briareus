from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from common.account_contracts import AccountList, InvocationEvent, InvocationEventBatch
from common.models import JsonObject
from common.oauth_session_contracts import OAuthSessionEvent
from management.application.services import (
    AccountService,
    InvocationAuditService,
    OAuthSessionService,
    RuntimeSettingsService,
)
from management.domain.accounts import Provider
from management.domain.telemetry import Invocation


class ApiServices:
    def __init__(
        self,
        accounts: AccountService,
        audit: InvocationAuditService,
        oauth_sessions: OAuthSessionService,
        runtime_settings: RuntimeSettingsService,
        service_token: str,
    ) -> None:
        self.accounts = accounts
        self.audit = audit
        self.oauth_sessions = oauth_sessions
        self.runtime_settings = runtime_settings
        self.service_token = service_token


def build_internal_router(services: ApiServices) -> APIRouter:
    router = APIRouter(prefix="/internal", tags=["internal"])

    def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {services.service_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    @router.get("/accounts")
    def list_accounts(
        provider: Annotated[Provider | None, Query()] = None,
        _authorized: None = Depends(authorize),
    ) -> JsonObject:
        accounts = services.accounts.list(provider=provider)
        return AccountList(accounts=accounts, count=len(accounts)).to_json()

    @router.get("/accounts/{selector}/resolve")
    def resolve_account(
        selector: str,
        provider: Provider,
        _authorized: None = Depends(authorize),
    ) -> JsonObject:
        try:
            return services.accounts.resolve(selector, provider=provider).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/runtime-settings/terminal")
    def terminal_runtime_settings(
        _authorized: None = Depends(authorize),
    ) -> JsonObject:
        return services.runtime_settings.terminal_policy().to_json()

    @router.get("/runtime-settings/mcp")
    def mcp_runtime_settings(
        _authorized: None = Depends(authorize),
    ) -> JsonObject:
        return services.runtime_settings.mcp_policy().to_json()

    @router.get("/runtime-settings/github")
    def github_runtime_settings(
        _authorized: None = Depends(authorize),
    ) -> JsonObject:
        return services.runtime_settings.github_policy().to_json()

    @router.post("/events", status_code=204)
    def record_event(
        event: InvocationEvent,
        _authorized: None = Depends(authorize),
    ) -> None:
        services.audit.record(Invocation.model_validate(event.model_dump()))

    @router.post("/events/batch", status_code=204)
    def record_event_batch(
        batch: InvocationEventBatch,
        _authorized: None = Depends(authorize),
    ) -> None:
        services.audit.record_many(
            [Invocation.model_validate(event.model_dump()) for event in batch.events]
        )

    @router.post("/oauth-sessions/events", status_code=204)
    def record_oauth_session(
        event: OAuthSessionEvent,
        _authorized: None = Depends(authorize),
    ) -> None:
        services.oauth_sessions.record(event)

    @router.get("/oauth-sessions/recent")
    def recent_oauth_sessions(
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
        _authorized: None = Depends(authorize),
    ) -> JsonObject:
        sessions = services.oauth_sessions.recent(limit=limit)
        return {
            "sessions": [
                {
                    **session.__dict__,
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                    "last_used_at": (
                        session.last_used_at.isoformat() if session.last_used_at else None
                    ),
                    "last_refresh_at": (
                        session.last_refresh_at.isoformat() if session.last_refresh_at else None
                    ),
                    "access_expires_at": (
                        session.access_expires_at.isoformat() if session.access_expires_at else None
                    ),
                    "refresh_expires_at": (
                        session.refresh_expires_at.isoformat()
                        if session.refresh_expires_at
                        else None
                    ),
                    "revoked_at": (session.revoked_at.isoformat() if session.revoked_at else None),
                }
                for session in sessions
            ],
            "count": len(sessions),
        }

    @router.get("/events/recent")
    def recent_events(
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        _authorized: None = Depends(authorize),
    ) -> JsonObject:
        events = services.audit.recent(limit=limit)
        return {
            "events": [event.model_dump(mode="json") for event in events],
            "count": len(events),
        }

    return router
