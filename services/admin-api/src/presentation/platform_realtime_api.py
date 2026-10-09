"""Private, unmounted Project/Team/User scoped realtime WebSocket source.

This is a C1-B2/C2 contract for B13, NOT an Internet/ASGI endpoint.
The caller's browser TLS/Origin and one-use connection credential require an
independently accepted handshake adapter. A User ID, old cookie or raw
WebSocket header is never proof of current platform identity.

The server never trusts a client-supplied snapshot, cursor, membership or
permission revision. Every requested batch reauthorizes from PostgreSQL.
No browser acknowledgement is claimed as a durable Gateway outbox ACK.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from authorization._platform_application import PlatformApplication
from authorization._project_access import CallerPrincipal
from authorization._scoped_events import (
    ScopeAccessRevoked,
    ScopeBatch,
    ScopedEventFeed,
    ScopeKey,
    ScopeResumeRequired,
    ScopeSubscription,
)
from common.platform_errors import AccessDenied, AuthenticationRequired

_SUBPROTOCOL = "briareus.scoped.v1"
_MAX_COMMAND_BYTES = 256


class AuthenticatedRealtimeHandshake(BaseModel):
    """Source-only evidence returned by a separately trusted C2 adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    caller: CallerPrincipal
    expires_at: datetime
    transport_attested: bool
    origin_attested: bool

    def require_current(self) -> CallerPrincipal:
        if (
            not self.transport_attested
            or not self.origin_attested
            or self.expires_at.tzinfo is None
            or self.expires_at <= datetime.now(UTC)
        ):
            raise AuthenticationRequired("verified realtime handshake expired or unavailable")
        return self.caller


class TrustedRealtimeHandshakePort(Protocol):
    async def authenticate(self, websocket: WebSocket) -> AuthenticatedRealtimeHandshake:
        """Verify one-use ticket, bearer/current JTI, TLS host/Origin out of band."""
        ...


class NextRealtimeBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["next"]
    limit: int = Field(default=64, ge=1, le=64)


class RealtimeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID
    scope_kind: str
    scope_id: UUID
    sequence: int = Field(ge=1)
    epoch: UUID
    event_type: str
    actor_user_id: UUID | None
    payload: dict[str, object]
    created_at: datetime


class RealtimeOffset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_kind: str
    scope_id: UUID
    epoch: UUID
    after_sequence: int = Field(ge=0)


class RealtimeEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["subscribed", "events"]
    subscription_id: UUID
    root_scope_kind: str
    root_scope_id: UUID
    permission_revision: str
    expires_at: datetime
    offsets: list[RealtimeOffset]
    events: list[RealtimeEvent]


def _offsets(batch: ScopeSubscription) -> list[RealtimeOffset]:
    return [
        RealtimeOffset(
            scope_kind=offset.scope.kind,
            scope_id=offset.scope.scope_id,
            epoch=offset.epoch,
            after_sequence=offset.after_sequence,
        )
        for offset in batch.offsets
    ]


def _envelope(
    subscription: ScopeSubscription,
    *,
    kind: Literal["subscribed", "events"],
    batch: ScopeBatch | None = None,
) -> RealtimeEnvelope:
    current = batch.subscription if batch is not None else subscription
    events = []
    if batch is not None:
        events = [
            RealtimeEvent(
                event_id=event.event_id,
                scope_kind=event.scope.kind,
                scope_id=event.scope.scope_id,
                sequence=event.sequence,
                epoch=event.epoch,
                event_type=event.event_type,
                actor_user_id=event.actor_user_id,
                payload=event.payload,
                created_at=event.created_at,
            )
            for event in batch.events
        ]
    return RealtimeEnvelope(
        kind=kind,
        subscription_id=current.subscriber_id,
        root_scope_kind=current.scope.kind,
        root_scope_id=current.scope.scope_id,
        permission_revision=current.decision_version,
        expires_at=current.expires_at,
        offsets=_offsets(current),
        events=events,
    )


def build_unmounted_private_realtime_router(
    application: PlatformApplication,
    feed: ScopedEventFeed,
    *,
    handshake: TrustedRealtimeHandshakePort | None = None,
) -> APIRouter:
    """No default C2 handshake; path remains completely UNMOUNTED by Admin."""
    router = APIRouter(tags=["private-scoped-realtime-source"])

    @router.websocket("/internal/v1/realtime/{scope_kind}/{scope_id}")
    async def scoped_realtime(
        websocket: WebSocket,
        scope_kind: Literal["project", "team", "user"],
        scope_id: UUID,
    ) -> None:
        if handshake is None:
            await websocket.close(code=4403)
            return
        try:
            protocols: object = websocket.scope.get("subprotocols")
            if not isinstance(protocols, list) or _SUBPROTOCOL not in protocols:
                raise AuthenticationRequired("verified scoped WebSocket protocol required")
            proof = await handshake.authenticate(websocket)
            if not isinstance(proof, AuthenticatedRealtimeHandshake):
                raise AuthenticationRequired("untrusted WebSocket connection identity")
            caller = proof.require_current()
            scope = ScopeKey(scope_kind, scope_id)
            async with application.db.transaction() as tx:
                subscription = await feed.subscribe(tx, caller, scope)
            await websocket.accept(subprotocol=_SUBPROTOCOL)
            await websocket.send_json(
                _envelope(subscription, kind="subscribed").model_dump(mode="json")
            )
            while True:
                proof.require_current()
                raw = await websocket.receive_text()
                if len(raw.encode("utf-8")) > _MAX_COMMAND_BYTES:
                    raise AccessDenied("realtime request length exceeded")
                next_batch = NextRealtimeBatch.model_validate_json(raw)
                async with application.db.transaction() as tx:
                    batch = await feed.poll(
                        tx,
                        caller,
                        subscription,
                        limit=next_batch.limit,
                    )
                subscription = batch.subscription
                await websocket.send_json(
                    _envelope(subscription, kind="events", batch=batch).model_dump(mode="json")
                )
        except WebSocketDisconnect:
            return
        except (AuthenticationRequired, AccessDenied, ScopeAccessRevoked):
            await websocket.close(code=4403)
        except ScopeResumeRequired:
            # Stale permission revision, changed owner or event retention gap.
            # The client must obtain a fresh authenticated snapshot, never
            # continue from a guessed cursor.
            await websocket.close(code=4409)
        except (ValueError, ValidationError):
            await websocket.close(code=4400)

    return router
