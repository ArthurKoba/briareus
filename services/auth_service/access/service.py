from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import valkey

from common.access_contracts import (
    AccessRequestView,
    AdminResolveRequest,
    AdminSessionUpdate,
    EnforcementMode,
    ExtensionRequest,
    FullAccessRequest,
    OAuthContext,
    SessionOpenRequest,
    SessionSnapshot,
    SessionUpdateRequest,
    SessionValidateRequest,
    ValidationResult,
)
from common.cache import SharedCache
from common.mcp_surfaces import is_account_backed_surface
from common.settings import AuthServiceSettings, ValkeySettings

from .events import AccessEventPublisher
from .repository import AccessRepository


@dataclass(frozen=True)
class AbuseResult:
    blocked: bool
    oauth_revoked: bool
    retry_after_seconds: int = 0


class AbuseGuard:
    def __init__(
        self,
        settings: AuthServiceSettings,
        cache_settings: ValkeySettings,
    ) -> None:
        self.settings = settings
        self._redis = valkey.Valkey.from_url(
            cache_settings.url,
            decode_responses=True,
            socket_connect_timeout=cache_settings.socket_connect_timeout_seconds,
            socket_timeout=cache_settings.socket_timeout_seconds,
            health_check_interval=30,
        )
        self._prefix = cache_settings.namespace.rstrip(":")

    def _key(self, oauth_session_id: str, surface_id: int) -> str:
        return f"{self._prefix}:access:abuse:{oauth_session_id}:{surface_id}"

    def failure(self, oauth_session_id: str, surface_id: int) -> tuple[int, int]:
        key = self._key(oauth_session_id, surface_id)
        try:
            with self._redis.pipeline() as pipe:
                pipe.incr(key)
                pipe.expire(key, self.settings.invalid_attempt_window_seconds)
                count_raw, _ = pipe.execute()  # type: ignore[no-untyped-call]
            count = int(count_raw)
        except (valkey.exceptions.ValkeyError, TypeError, ValueError):
            return 0, 0

        if count < self.settings.invalid_attempt_soft_limit:
            return count, 0
        return count, self.settings.invalid_attempt_backoff_seconds

    def clear(self, oauth_session_id: str, surface_id: int) -> None:
        try:
            self._redis.delete(self._key(oauth_session_id, surface_id))
        except valkey.exceptions.ValkeyError:
            return


class AccessService:
    def __init__(
        self,
        *,
        settings: AuthServiceSettings,
        repository: AccessRepository,
        cache: SharedCache,
        cache_settings: ValkeySettings,
        events: AccessEventPublisher | None = None,
        revoke_oauth_session: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.cache = cache
        self.events = events
        self.abuse = AbuseGuard(settings, cache_settings)
        self._revoke_oauth_session_callback = revoke_oauth_session

    async def close(self) -> None:
        if self.events is not None:
            await self.events.close()

    def _session_key(self, uid: str) -> str:
        return self.cache.key("access", "session", uid)

    def _control_key(self, user_id: str, surface_id: int) -> str:
        return self.cache.key("access", "control", user_id, str(surface_id))

    def _session_cache_ttl(self, session: SessionSnapshot) -> int:
        if session.expires_at == 0:
            return self.settings.cache_ttl_seconds
        remaining = session.expires_at - int(time.time())
        return max(1, min(self.settings.cache_ttl_seconds, remaining))

    async def _cache_session(self, session: SessionSnapshot) -> None:
        if session.status != "active":
            await asyncio.to_thread(self.cache.delete, self._session_key(session.uid))
            return
        await asyncio.to_thread(
            self.cache.set_json,
            self._session_key(session.uid),
            session.model_dump(mode="json"),
            ttl_seconds=self._session_cache_ttl(session),
        )

    async def _load_session(self, uid: str) -> SessionSnapshot | None:
        key = self._session_key(uid)
        cached = await asyncio.to_thread(self.cache.get_json, key)
        if isinstance(cached, dict):
            try:
                snapshot = SessionSnapshot.model_validate(cached)
            except Exception:
                await asyncio.to_thread(self.cache.delete, key)
            else:
                expired = (
                    snapshot.status == "active"
                    and snapshot.expires_at > 0
                    and snapshot.expires_at <= int(time.time())
                )
                if not expired:
                    return snapshot
                await asyncio.to_thread(self.cache.delete, key)

        session = await self.repository.get_session(uid)
        if session is not None:
            await self._cache_session(session)
        return session

    async def _invalidate_session(self, uid: str) -> None:
        await asyncio.to_thread(self.cache.delete, self._session_key(uid))

    def _oauth_block_key(self, oauth_session_id: str) -> str:
        return self.cache.key("access", "oauth-block", oauth_session_id)

    async def _oauth_context_blocked(self, oauth_session_id: str, user_id: str) -> bool:
        key = self._oauth_block_key(oauth_session_id)
        cached = await asyncio.to_thread(self.cache.get_json, key)
        if isinstance(cached, bool):
            return cached
        blocked = await self.repository.oauth_context_blocked(
            oauth_session_id, user_id=user_id
        )
        await asyncio.to_thread(
            self.cache.set_json,
            key,
            blocked,
            ttl_seconds=self.settings.cache_ttl_seconds,
        )
        return blocked

    async def get_mode(self, user_id: str, surface_id: int) -> EnforcementMode:
        key = self._control_key(user_id, surface_id)
        cached = await asyncio.to_thread(self.cache.get_json, key)
        if cached in {"unrestricted", "session_enforced"}:
            return cached  # type: ignore[return-value]
        mode = await self.repository.get_mode(user_id, surface_id)
        await asyncio.to_thread(
            self.cache.set_json,
            key,
            mode,
            ttl_seconds=self.settings.cache_ttl_seconds,
        )
        return mode

    async def set_mode(
        self,
        *,
        user_id: str,
        surface_id: int,
        mode: EnforcementMode,
    ) -> EnforcementMode:
        resolved = await self.repository.set_mode(
            user_id=user_id,
            surface_id=surface_id,
            mode=mode,
        )
        await asyncio.to_thread(self.cache.delete, self._control_key(user_id, surface_id))
        return resolved

    async def set_modes_batch(
        self,
        items: list[tuple[str, int, EnforcementMode]],
    ) -> list[tuple[str, int, EnforcementMode]]:
        resolved = await self.repository.set_modes_batch(items)
        for user_id, surface_id, _mode in resolved:
            await asyncio.to_thread(
                self.cache.delete, self._control_key(user_id, surface_id)
            )
        return resolved

    async def _require_oauth_context_active(self, context: OAuthContext) -> None:
        if await self._oauth_context_blocked(
            context.oauth_session_id, context.user_id
        ):
            raise PermissionError("oauth_session_revoked")

    async def open_session(self, request: SessionOpenRequest) -> SessionSnapshot:
        await self._require_oauth_context_active(request)
        session = await self.repository.open_session(
            user_id=request.user_id,
            client_id=request.client_id,
            oauth_session_id=request.oauth_session_id,
            surface_id=request.surface_id,
            ttl_seconds=self.settings.default_session_ttl_seconds,
            label=request.label,
        )
        await self._cache_session(session)
        if self.events is not None:
            await self.events.publish(
                "session_opened",
                {
                    "session_id": session.id,
                    "surface_id": session.surface_id,
                    "user_id": session.user_id,
                    "status": session.status,
                },
            )
        return session

    async def reissue_session(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        old_uid: str,
        label: str = "",
    ) -> SessionSnapshot:
        old = await self._load_session(old_uid)
        if (
            old is not None
            and old.status == "active"
            and (old.expires_at == 0 or old.expires_at > int(time.time()))
        ):
            raise ValueError("active session cannot be reissued")
        return await self.open_session(
            SessionOpenRequest(
                user_id=context.user_id,
                client_id=context.client_id,
                oauth_session_id=context.oauth_session_id,
                surface_id=surface_id,
                label=label,
            )
        )

    async def validate(self, request: SessionValidateRequest) -> ValidationResult:
        if await self._oauth_context_blocked(
            request.oauth_session_id, request.user_id
        ):
            return ValidationResult(allowed=False, code="oauth_session_revoked")

        mode = await self.get_mode(request.user_id, request.surface_id)
        if mode == "unrestricted":
            self.abuse.clear(request.oauth_session_id, request.surface_id)
            return ValidationResult(allowed=True, code="unrestricted")

        if not request.session_uid:
            return ValidationResult(allowed=False, code="session_required")

        session = await self._load_session(request.session_uid)
        if not self._matches_context(session, request):
            abuse = await self._record_invalid_attempt(request)
            return ValidationResult(
                allowed=False,
                code="rate_limited" if abuse.blocked else "session_invalid",
                retry_after_seconds=abuse.retry_after_seconds,
            )

        assert session is not None
        if session.status != "active":
            return ValidationResult(
                allowed=False,
                code=f"session_{session.status}",
                session=session,
            )
        if session.expires_at > 0 and session.expires_at <= int(time.time()):
            await self._invalidate_session(session.uid)
            return ValidationResult(allowed=False, code="session_expired", session=session)

        if request.requires_full_access and session.access_level != "full_access":
            return ValidationResult(
                allowed=False,
                code="full_access_required",
                session=session,
            )
        if request.requires_full_access and is_account_backed_surface(
            request.surface_id
        ):
            if session.account_scope == "none":
                return ValidationResult(
                    allowed=False,
                    code="account_scope_denied",
                    session=session,
                )
            if session.account_scope == "selected" and (
                not request.account_id
                or request.account_id not in session.account_ids
            ):
                return ValidationResult(
                    allowed=False,
                    code="account_scope_denied",
                    session=session,
                )

        self.abuse.clear(request.oauth_session_id, request.surface_id)
        return ValidationResult(allowed=True, code="allowed", session=session)

    @staticmethod
    def _matches_context(
        session: SessionSnapshot | None,
        request: SessionValidateRequest,
    ) -> bool:
        return bool(
            session is not None
            and session.user_id == request.user_id
            and session.oauth_client_id == request.client_id
            and session.oauth_session_id == request.oauth_session_id
            and session.surface_id == request.surface_id
        )

    async def _record_invalid_attempt(
        self,
        request: SessionValidateRequest,
    ) -> AbuseResult:
        count, retry_after = await asyncio.to_thread(
            self.abuse.failure,
            request.oauth_session_id,
            request.surface_id,
        )
        await self.repository.record_security_event(
            user_id=request.user_id,
            oauth_session_id=request.oauth_session_id,
            surface_id=request.surface_id,
            event_type="invalid_session_attempt",
            details={"count": count, "tool": request.tool_name},
        )
        oauth_revoked = False
        if count >= self.settings.invalid_attempt_oauth_revoke_limit:
            await self.repository.block_oauth_context(
                oauth_session_id=request.oauth_session_id,
                user_id=request.user_id,
                reason="invalid_session_abuse",
            )
            await asyncio.to_thread(
                self.cache.set_json,
                self._oauth_block_key(request.oauth_session_id),
                True,
                ttl_seconds=self.settings.cache_ttl_seconds,
            )
            oauth_revoked = await self._revoke_oauth_session(request.oauth_session_id)
            await self.repository.record_security_event(
                user_id=request.user_id,
                oauth_session_id=request.oauth_session_id,
                surface_id=request.surface_id,
                event_type="oauth_revoked_for_session_abuse",
                details={"count": count},
            )
        return AbuseResult(
            blocked=retry_after > 0,
            oauth_revoked=oauth_revoked,
            retry_after_seconds=retry_after,
        )

    async def _revoke_oauth_session(self, oauth_session_id: str) -> bool:
        if self._revoke_oauth_session_callback is None:
            return False
        await self._revoke_oauth_session_callback(oauth_session_id)
        return True

    async def status(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        uid: str,
    ) -> SessionSnapshot | None:
        session = await self._load_session(uid)
        if session is None:
            return None
        if (
            session.user_id != context.user_id
            or session.oauth_client_id != context.client_id
            or session.oauth_session_id != context.oauth_session_id
            or session.surface_id != surface_id
        ):
            return None
        return session

    async def update_session(
        self,
        request: SessionUpdateRequest,
    ) -> SessionSnapshot:
        session = await self.status(
            context=request,
            surface_id=request.surface_id,
            uid=request.session_uid,
        )
        if session is None:
            raise ValueError("agent session not found")
        updated = await self.repository.update_label(session.id, request.label)
        if updated is None:
            raise ValueError("agent session not found")
        await self._invalidate_session(updated.uid)
        await self._cache_session(updated)
        return updated

    async def request_full_access(
        self,
        request: FullAccessRequest,
    ) -> AccessRequestView:
        await self._require_oauth_context_active(request)
        session = await self.status(
            context=request,
            surface_id=request.surface_id,
            uid=request.session_uid,
        )
        if session is None or session.status != "active":
            raise ValueError("active agent session not found")
        if request.account_scope == "selected" and not request.account_ids:
            raise ValueError("selected account scope requires account_ids")
        pending = await self.repository.create_request(
            session_id=session.id,
            kind="full_access",
            requested_access_level="full_access",
            account_scope=request.account_scope,
            account_ids=request.account_ids,
        )
        if self.events is not None:
            await self.events.publish(
                "full_access_requested",
                {
                    "request_id": pending.id,
                    "session_id": session.id,
                    "surface_id": session.surface_id,
                    "user_id": session.user_id,
                },
            )
        return pending

    async def request_extension(
        self,
        request: ExtensionRequest,
    ) -> AccessRequestView:
        await self._require_oauth_context_active(request)
        session = await self.status(
            context=request,
            surface_id=request.surface_id,
            uid=request.session_uid,
        )
        if session is None or session.status != "active":
            raise ValueError("active agent session not found")
        pending = await self.repository.create_request(
            session_id=session.id,
            kind="extension",
            requested_expires_at=request.requested_expires_at,
        )
        if self.events is not None:
            await self.events.publish(
                "extension_requested",
                {
                    "request_id": pending.id,
                    "session_id": session.id,
                    "surface_id": session.surface_id,
                    "user_id": session.user_id,
                },
            )
        return pending

    async def close_session(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        uid: str,
    ) -> SessionSnapshot:
        session = await self.status(context=context, surface_id=surface_id, uid=uid)
        if session is None:
            raise ValueError("agent session not found")
        revoked = await self.repository.revoke_session(session.id)
        if revoked is None:
            raise ValueError("agent session not found")
        await self._invalidate_session(uid)
        if self.events is not None:
            await self.events.publish(
                "session_closed",
                {
                    "session_id": revoked.id,
                    "surface_id": revoked.surface_id,
                    "user_id": revoked.user_id,
                },
            )
        return revoked

    async def resolve_request(
        self,
        request_id: str,
        request: AdminResolveRequest,
    ) -> tuple[AccessRequestView, SessionSnapshot]:
        resolved, session = await self.repository.resolve_request(
            request_id,
            admin_user_id=request.admin_user_id,
            approve=request.approve,
            account_scope=request.account_scope,
            account_ids=request.account_ids,
            expires_at=request.expires_at,
        )
        await self._invalidate_session(session.uid)
        await self._cache_session(session)
        return resolved, session

    async def admin_update(
        self, session_id: str, request: AdminSessionUpdate
    ) -> SessionSnapshot:
        current = await self.repository.get_session_by_id(session_id)
        if current is None or current.user_id != request.admin_user_id:
            raise ValueError("agent session not found")
        effective_scope = request.account_scope or current.account_scope
        effective_ids = (
            request.account_ids
            if request.account_ids is not None
            else current.account_ids
        )
        if effective_scope == "selected" and not effective_ids:
            raise ValueError("selected account scope requires account_ids")
        updated = await self.repository.admin_update_session(
            session_id,
            admin_user_id=request.admin_user_id,
            access_level=request.access_level,
            account_scope=request.account_scope,
            account_ids=request.account_ids,
            expires_at=request.expires_at,
            label=request.label,
        )
        if updated is None:
            raise ValueError("agent session not found")
        await self._invalidate_session(updated.uid)
        await self._cache_session(updated)
        return updated

    async def admin_revoke(
        self, session_id: str, *, admin_user_id: str
    ) -> SessionSnapshot:
        session = await self.repository.get_session_by_id(session_id)
        if session is None or session.user_id != admin_user_id:
            raise ValueError("agent session not found")
        revoked = await self.repository.revoke_session(session_id)
        if revoked is None:
            raise ValueError("agent session not found")
        await self._invalidate_session(revoked.uid)
        return revoked
