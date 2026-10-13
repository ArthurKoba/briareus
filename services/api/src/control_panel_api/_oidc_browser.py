"""Browser OIDC code+PKCE with single-use private Valkey transactions.

Neither Rauthy OAuth identity nor this short-lived browser session is a
Briareus Platform User, Project membership or Authorization/Cedar grant.
"""

from __future__ import annotations

import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import SecretStr
from valkey.asyncio import Valkey
from valkey.exceptions import ValkeyError

from ._oidc import OidcProviderUnavailable, RauthyOidcAdapter
from ._oidc_id_token import (
    OidcIdentityKeysUnavailable,
    OidcIdentityRejected,
    VerifiedOidcIdentity,
)

_ORIGIN = "https://briareus.koba-nexus.ru"
_CALLBACK = _ORIGIN + "/api/auth/oidc/callback"
_PANEL = _ORIGIN + "/panel/"
_TX_COOKIE = "__Host-briareus_oidc_transaction"
_SID_COOKIE = "__Host-briareus_oidc_session"
_MAX_IDENTITY_SECONDS = 900
_MAX_TRANSACTION_SECONDS = 300
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,128}")


class OidcSessionStoreUnavailable(Exception):
    """Trusted private transaction/session store did not confirm an operation."""


@dataclass(frozen=True, slots=True)
class PanelOidcSession:
    issuer: str
    subject: str
    client_id: str
    expires_at: datetime


class OidcBrowserSessionStore:
    def __init__(self, *, password: SecretStr, client: Valkey | None = None) -> None:
        raw = password.get_secret_value()
        if re.fullmatch(r"[a-f0-9]{64}", raw) is None:
            raise ValueError("OIDC transaction store requires the protected Valkey credential")
        self._client = client or Valkey(
            host="briareus-valkey",
            port=6379,
            password=raw,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
            health_check_interval=30,
        )
        self._owned = client is None

    async def close(self) -> None:
        if self._owned:
            await self._client.aclose()

    @staticmethod
    def _key(scope: str, token: str) -> str:
        if _TOKEN.fullmatch(token) is None:
            raise ValueError("untrusted OIDC browser token")
        return "briareus:panel:oidc:" + scope + ":" + sha256(token.encode("ascii")).hexdigest()

    async def save_transaction(self, *, state: str, nonce: str, verifier: str) -> None:
        key = self._key("transaction", state)
        try:
            created = await self._client.set(
                key,
                json.dumps({"nonce": nonce, "verifier": verifier}, separators=(",", ":")),
                ex=_MAX_TRANSACTION_SECONDS,
                nx=True,
            )
        except ValkeyError as exc:
            raise OidcSessionStoreUnavailable("OIDC transaction store unavailable") from exc
        if not created:
            raise OidcSessionStoreUnavailable("OIDC transaction collision")

    async def consume_transaction(self, *, state: str) -> tuple[str, SecretStr] | None:
        try:
            raw = await self._client.getdel(self._key("transaction", state))
        except ValkeyError as exc:
            raise OidcSessionStoreUnavailable("OIDC transaction store unavailable") from exc
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            nonce, verifier = payload["nonce"], payload["verifier"]
            if (
                not isinstance(nonce, str)
                or _TOKEN.fullmatch(nonce) is None
                or not isinstance(verifier, str)
                or _TOKEN.fullmatch(verifier) is None
            ):
                return None
            return nonce, SecretStr(verifier)
        except (ValueError, TypeError, KeyError):
            return None

    async def create_session(self, identity: VerifiedOidcIdentity) -> tuple[str, int]:
        now = datetime.now(UTC)
        seconds = min(int((identity.expires_at - now).total_seconds()), _MAX_IDENTITY_SECONDS)
        if seconds < 1:
            raise OidcSessionStoreUnavailable("Rauthy identity already expired")
        ticket = secrets.token_urlsafe(48)
        value = json.dumps(
            {
                "issuer": identity.issuer,
                "subject": identity.subject,
                "client_id": identity.client_id,
                "expires_at": identity.expires_at.isoformat(),
            },
            separators=(",", ":"),
        )
        try:
            created = await self._client.set(
                self._key("session", ticket), value, ex=seconds, nx=True
            )
        except ValkeyError as exc:
            raise OidcSessionStoreUnavailable("OIDC session store unavailable") from exc
        if not created:
            raise OidcSessionStoreUnavailable("OIDC session collision")
        return ticket, seconds

    async def get_session(self, ticket: str) -> PanelOidcSession | None:
        try:
            raw = await self._client.get(self._key("session", ticket))
        except ValkeyError as exc:
            raise OidcSessionStoreUnavailable("OIDC session store unavailable") from exc
        if raw is None:
            return None
        try:
            item = json.loads(raw)
            identity = PanelOidcSession(
                issuer=item["issuer"],
                subject=item["subject"],
                client_id=item["client_id"],
                expires_at=datetime.fromisoformat(item["expires_at"]),
            )
            if (
                not identity.subject
                or identity.expires_at.tzinfo is None
                or identity.expires_at <= datetime.now(UTC)
            ):
                return None
            return identity
        except (ValueError, TypeError, KeyError):
            return None

    async def delete_session(self, ticket: str) -> None:
        try:
            await self._client.delete(self._key("session", ticket))
        except ValkeyError as exc:
            raise OidcSessionStoreUnavailable("OIDC logout could not be committed") from exc


def _cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _clear(response: Response, name: str) -> None:
    response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")


def oidc_browser_router(
    provider: RauthyOidcAdapter,
    sessions: OidcBrowserSessionStore,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/auth/oidc/start")
    async def start() -> Response:
        try:
            attempt = await provider.prepare_authorization_code(redirect_uri=_CALLBACK)
            await sessions.save_transaction(
                state=attempt.state,
                nonce=attempt.nonce,
                verifier=attempt.code_verifier.get_secret_value(),
            )
        except (OidcProviderUnavailable, OidcSessionStoreUnavailable) as exc:
            raise HTTPException(503, detail="OIDC login unavailable") from exc
        response = RedirectResponse(attempt.authorization_url, status_code=302, headers=_NO_STORE)
        _cookie(response, _TX_COOKIE, attempt.state, _MAX_TRANSACTION_SECONDS)
        return response

    @router.get("/api/auth/oidc/callback")
    async def callback(request: Request) -> Response:
        args = request.query_params
        states = args.getlist("state")
        codes = args.getlist("code")
        if (
            len(states) != 1
            or len(codes) != 1
            or _TOKEN.fullmatch(states[0]) is None
            or not 1 <= len(codes[0]) <= 4096
            or any(ch.isspace() for ch in codes[0])
        ):
            raise HTTPException(400, detail="invalid OIDC authorization callback")
        original = request.cookies.get(_TX_COOKIE, "")
        if _TOKEN.fullmatch(original) is None or not hmac.compare_digest(original, states[0]):
            raise HTTPException(401, detail="OIDC state mismatch")
        try:
            transaction = await sessions.consume_transaction(state=states[0])
            if transaction is None:
                raise HTTPException(401, detail="OIDC state already used or expired")
            nonce, verifier = transaction
            tokens = await provider.exchange_authorization_code(
                code=codes[0], redirect_uri=_CALLBACK, code_verifier=verifier
            )
            identity = await provider.verify_exchanged_id_token(tokens=tokens, expected_nonce=nonce)
            ticket, age = await sessions.create_session(identity)
        except (
            OidcProviderUnavailable,
            OidcIdentityKeysUnavailable,
            OidcSessionStoreUnavailable,
        ) as exc:
            raise HTTPException(503, detail="OIDC identity service unavailable") from exc
        except OidcIdentityRejected as exc:
            raise HTTPException(401, detail="OIDC identity verification failed") from exc
        response = RedirectResponse(_PANEL, status_code=303, headers=_NO_STORE)
        _clear(response, _TX_COOKIE)
        _cookie(response, _SID_COOKIE, ticket, age)
        return response

    @router.get("/api/auth/oidc/session")
    async def current_session(request: Request) -> Response:
        sid = request.cookies.get(_SID_COOKIE, "")
        if _TOKEN.fullmatch(sid) is None:
            raise HTTPException(401, detail="OIDC browser session required")
        try:
            identity = await sessions.get_session(sid)
        except OidcSessionStoreUnavailable as exc:
            raise HTTPException(503, detail="OIDC session store unavailable") from exc
        if identity is None:
            raise HTTPException(401, detail="OIDC browser session expired")
        # Identity-only. Never replace /api/platform/me or invent Project grants.
        return JSONResponse(
            {
                "authenticated": True,
                "authority": "rauthy",
                "subject": identity.subject,
                "issuer": identity.issuer,
                "client_id": identity.client_id,
                "expires_at": identity.expires_at.isoformat(),
                "platform_membership_verified": False,
                "permissions": [],
            },
            headers=_NO_STORE,
        )

    @router.post("/api/auth/oidc/logout")
    async def logout(request: Request) -> Response:
        if request.headers.getlist("origin") != [_ORIGIN]:
            raise HTTPException(403, detail="same-origin logout required")
        sid = request.cookies.get(_SID_COOKIE, "")
        if _TOKEN.fullmatch(sid) is not None:
            try:
                await sessions.delete_session(sid)
            except OidcSessionStoreUnavailable as exc:
                raise HTTPException(503, detail="OIDC logout not confirmed") from exc
        response = Response(status_code=204, headers=_NO_STORE)
        _clear(response, _SID_COOKIE)
        _clear(response, _TX_COOKIE)
        return response

    return router
