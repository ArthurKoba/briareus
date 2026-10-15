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
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import SecretStr
from valkey.asyncio import Valkey
from valkey.exceptions import ValkeyError

from ._api_paths import AUTH_API_PREFIX, REGISTERED_RAUTHY_CALLBACK_PATH
from ._native_state_scripts import CANCEL_LOGIN, CLAIM_INIT, COMPLETE_LOGIN, CONFIRM_POW
from ._oidc import OidcProviderUnavailable, RauthyOidcAdapter, _unique_oidc_fields
from ._oidc_id_token import (
    OidcIdentityKeysUnavailable,
    OidcIdentityRejected,
    VerifiedOidcIdentity,
)
from ._oidc_origin_policy import (
    local_browser_host,
    resolve_browser_origin,
    validate_files_resource_intent,
)
from ._oidc_resource import PrivateOidcResourceCredential

_TX_COOKIE = "__Host-briareus_oidc_transaction"
_NATIVE_TX_COOKIE = "__Host-briareus_native_transaction"
_SID_COOKIE = "__Host-briareus_oidc_session"
_MAX_IDENTITY_SECONDS = 900
_MAX_TRANSACTION_SECONDS = 300
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,128}")
_PANEL_HANDLES = frozenset({_TX_COOKIE, _NATIVE_TX_COOKIE, _SID_COOKIE})


def _strict_browser_cookies(request: Request) -> dict[str, str] | None:
    """Read a SINGLE, unambiguous browser Cookie header for Panel state.

    Starlette's request.cookies silently picks a value from duplicate cookie
    names; that can make a cancelled/logout session appear current to another
    route. All three Panel handles are generated as unquoted opaque tokens.
    Return None for ambiguity, not a guessed cookie or empty authenticated
    state. Other application cookies are ignored, never made authoritative.
    """
    raw = request.headers.getlist("cookie")
    if len(raw) > 1 or (raw and len(raw[0]) > 8192):
        return None
    if not raw:
        return {}
    result: dict[str, str] = {}
    for entry in raw[0].split(";"):
        name, separator, value = entry.strip().partition("=")
        if name not in _PANEL_HANDLES:
            continue
        if not separator or name in result or _TOKEN.fullmatch(value) is None:
            return None
        result[name] = value
    return result


class OidcSessionStoreUnavailable(Exception):
    """Trusted private transaction/session store did not confirm an operation."""


@dataclass(frozen=True, slots=True)
class PanelOidcSession:
    issuer: str
    subject: str
    client_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PrivateOidcPending:
    nonce: str
    verifier: SecretStr
    issuer: str
    client_id: str
    resource_audience: str | None
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PrivateNativePending:
    """Server-held native Init transaction, not an authenticated User."""

    state: str
    issuer: str
    client_id: str
    nonce: str
    verifier: SecretStr
    csrf: SecretStr
    provider_cookie: SecretStr
    expires_at: datetime
    claim_id: SecretStr
    resource_audience: str | None = None


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

    async def save_transaction(
        self,
        *,
        state: str,
        nonce: str,
        verifier: str,
        issuer: str,
        client_id: str,
        resource_audience: str | None = None,
    ) -> None:
        validate_files_resource_intent(
            issuer=issuer, client_id=client_id, resource_audience=resource_audience
        )
        key = self._key("transaction", state)
        payload = {
            "nonce": nonce,
            "verifier": verifier,
            "issuer": issuer,
            "client_id": client_id,
            "resource_audience": resource_audience,
            "expires_at": (
                datetime.now(UTC) + timedelta(seconds=_MAX_TRANSACTION_SECONDS)
            ).isoformat(),
        }
        try:
            created = await self._client.set(
                key,
                json.dumps(payload, separators=(",", ":")),
                ex=_MAX_TRANSACTION_SECONDS,
                nx=True,
            )
        except ValkeyError as exc:
            raise OidcSessionStoreUnavailable("OIDC transaction store unavailable") from exc
        if not created:
            raise OidcSessionStoreUnavailable("OIDC transaction collision")

    async def save_native_init(
        self,
        *,
        state: str,
        nonce: str,
        verifier: str,
        issuer: str,
        client_id: str,
        csrf: SecretStr,
        provider_cookie: SecretStr,
        seconds: int,
        resource_audience: str | None = None,
    ) -> None:
        """Escrow once per state; never forward provider session to browser."""
        if (
            _TOKEN.fullmatch(state) is None
            or _TOKEN.fullmatch(nonce) is None
            or _TOKEN.fullmatch(verifier) is None
            or type(seconds) is not int
            or not 1 <= seconds <= _MAX_TRANSACTION_SECONDS
            or not isinstance(csrf, SecretStr)
            or not isinstance(provider_cookie, SecretStr)
            or not issuer.startswith("https://")
            or not client_id
        ):
            raise OidcSessionStoreUnavailable("untrusted native Init escrow")
        validate_files_resource_intent(
            issuer=issuer, client_id=client_id, resource_audience=resource_audience
        )
        deadline = datetime.now(UTC) + timedelta(seconds=seconds)
        payload = json.dumps(
            {
                "stage": "init",
                "deadline_ms": int(deadline.timestamp() * 1000),
                "state": state,
                "expires_at": deadline.isoformat(),
                "resource_audience": resource_audience,
                "nonce": nonce,
                "verifier": verifier,
                "issuer": issuer,
                "client_id": client_id,
                "csrf": csrf.get_secret_value(),
                "provider_cookie": provider_cookie.get_secret_value(),
            },
            separators=(",", ":"),
        )
        try:
            created = await self._client.set(
                self._key("native-init", state),
                payload,
                ex=seconds,
                nx=True,
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native Rauthy Init store unavailable") from None
        if not created:
            raise OidcSessionStoreUnavailable("native Rauthy Init collision")

    async def native_init_is_current(self, *, state: str, issuer: str, client_id: str) -> bool:
        try:
            raw = await self._client.get(self._key("native-init", state))
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native Init state unavailable") from None
        if raw is None or not isinstance(raw, str) or len(raw) > 16_384:
            return False
        try:
            payload = json.loads(raw, object_pairs_hook=_unique_oidc_fields)
            expires = datetime.fromisoformat(payload["expires_at"])
            if expires.tzinfo is None or expires <= datetime.now(UTC):
                return False
        except (ValueError, TypeError, KeyError):
            return False
        return bool(
            isinstance(payload, dict)
            and payload.get("stage") == "init"
            and payload.get("state") == state
            and payload.get("issuer") == issuer
            and payload.get("client_id") == client_id
            and isinstance(payload.get("csrf"), str)
            and re.fullmatch(r"[A-Za-z0-9]{32}", payload["csrf"]) is not None
            and isinstance(payload.get("provider_cookie"), str)
            and payload["provider_cookie"].startswith("__Host-RauthySession=")
        )

    async def reserve_native_pow(self, *, state: str, issuer: str, client_id: str) -> bool:
        """Claim at most one public PoW challenge per pending Init attempt.

        This is NOT provider authentication: atomic NX caps the number of
        challenge issuances even when two callers race on the same cookie.
        The pending Init must be rechecked after NX in case logout removed
        it concurrently. Failure burns the reservation (fail-closed).
        """
        if not await self.native_init_is_current(state=state, issuer=issuer, client_id=client_id):
            return False
        try:
            reserved = await self._client.set(
                self._key("native-pow", state),
                "reserved",
                nx=True,
                ex=_MAX_TRANSACTION_SECONDS,
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native PoW reservation unavailable") from None
        if not reserved:
            return False
        return await self.native_init_is_current(state=state, issuer=issuer, client_id=client_id)

    async def confirm_native_pow(self, *, state: str, issuer: str, client_id: str) -> bool:
        """Mark successful upstream issuance, not an earlier in-flight reservation."""
        try:
            result = await self._client.eval(
                CONFIRM_POW,
                2,
                self._key("native-init", state),
                self._key("native-pow", state),
                issuer,
                client_id,
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native PoW confirmation unavailable") from None
        return type(result) is int and result == 1

    async def consume_native_init(
        self, *, state: str, issuer: str, client_id: str
    ) -> PrivateNativePending | None:
        """Atomically claim once while retaining a cancelable, secret-free marker."""
        claim = secrets.token_urlsafe(32)
        try:
            raw = await self._client.eval(
                CLAIM_INIT,
                2,
                self._key("native-init", state),
                self._key("native-pow", state),
                issuer,
                client_id,
                claim,
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native Init claim unavailable") from None
        if not isinstance(raw, str) or len(raw) > 16_384:
            return None
        try:
            value = json.loads(raw, object_pairs_hook=_unique_oidc_fields)
            expires = datetime.fromisoformat(value["expires_at"])
            validate_files_resource_intent(
                issuer=issuer, client_id=client_id, resource_audience=value.get("resource_audience")
            )
            if (
                expires.tzinfo is None
                or expires <= datetime.now(UTC)
                or value.get("state") != state
                or value.get("issuer") != issuer
                or value.get("client_id") != client_id
                or not isinstance(value.get("nonce"), str)
                or _TOKEN.fullmatch(value["nonce"]) is None
                or not isinstance(value.get("verifier"), str)
                or _TOKEN.fullmatch(value["verifier"]) is None
                or not isinstance(value.get("csrf"), str)
                or re.fullmatch(r"[A-Za-z0-9]{32}", value["csrf"]) is None
                or not isinstance(value.get("provider_cookie"), str)
                or not re.fullmatch(
                    r"__Host-RauthySession=[!-~]{32,4096}", value["provider_cookie"]
                )
                or ";" in value["provider_cookie"]
            ):
                return None
            return PrivateNativePending(
                state=state,
                issuer=issuer,
                client_id=client_id,
                nonce=value["nonce"],
                verifier=SecretStr(value["verifier"]),
                csrf=SecretStr(value["csrf"]),
                provider_cookie=SecretStr(value["provider_cookie"]),
                expires_at=expires,
                claim_id=SecretStr(claim),
                resource_audience=value.get("resource_audience"),
            )
        except (ValueError, TypeError, KeyError):
            return None

    async def native_claim_is_current(self, pending: PrivateNativePending) -> bool:
        try:
            raw = await self._client.get(self._key("native-init", pending.state))
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native claim state unavailable") from None
        if not isinstance(raw, str) or len(raw) > 4096:
            return False
        try:
            value = json.loads(raw, object_pairs_hook=_unique_oidc_fields)
            return (
                value.get("stage") == "claimed"
                and value.get("claim") == pending.claim_id.get_secret_value()
                and pending.expires_at > datetime.now(UTC)
            )
        except (ValueError, AttributeError, TypeError):
            return False

    async def complete_native_login(
        self,
        *,
        pending: PrivateNativePending,
        identity: VerifiedOidcIdentity,
        resource: PrivateOidcResourceCredential | None = None,
    ) -> tuple[str, int] | None:
        if (
            identity.issuer.rstrip("/") != pending.issuer.rstrip("/")
            or identity.client_id != pending.client_id
            or (resource.audience if resource else None) != pending.resource_audience
            or pending.expires_at <= datetime.now(UTC)
        ):
            return None
        ticket, seconds, value, deadline = self._prepare_session(identity, resource=resource)
        try:
            result = await self._client.eval(
                COMPLETE_LOGIN,
                2,
                self._key("native-init", pending.state),
                self._key("session", ticket),
                pending.claim_id.get_secret_value(),
                value,
                int(deadline.timestamp() * 1000),
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native session completion unavailable") from None
        if result == -1:
            raise OidcSessionStoreUnavailable("native session collision")
        if type(result) is not int or result != 1:
            return None
        return ticket, seconds

    async def delete_native_init(self, *, state: str) -> None:
        """Cancel init/claim OR its completed session before clearing browser state."""
        try:
            result = await self._client.eval(
                CANCEL_LOGIN,
                2,
                self._key("native-init", state),
                self._key("native-pow", state),
                "briareus:panel:oidc:session:",
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native login cancellation unavailable") from None
        if type(result) is not int or result != 1:
            raise OidcSessionStoreUnavailable("native cancellation linkage invalid")

    async def consume_transaction(
        self, *, state: str, issuer: str, client_id: str, resource_audience: str | None
    ) -> PrivateOidcPending | None:
        try:
            raw = await self._client.getdel(self._key("transaction", state))
        except ValkeyError as exc:
            raise OidcSessionStoreUnavailable("OIDC transaction store unavailable") from exc
        if raw is None or not isinstance(raw, str) or len(raw) > 16384:
            return None
        try:
            value = json.loads(raw, object_pairs_hook=_unique_oidc_fields)
            nonce, verifier = value["nonce"], value["verifier"]
            expires = datetime.fromisoformat(value["expires_at"])
            if (
                not isinstance(nonce, str)
                or _TOKEN.fullmatch(nonce) is None
                or not isinstance(verifier, str)
                or _TOKEN.fullmatch(verifier) is None
                or value["issuer"] != issuer
                or value["client_id"] != client_id
                or value["resource_audience"] != resource_audience
                or expires.tzinfo is None
                or expires <= datetime.now(UTC)
            ):
                return None
            return PrivateOidcPending(
                nonce, SecretStr(verifier), issuer, client_id, resource_audience, expires
            )
        except (ValueError, TypeError, KeyError):
            return None

    @staticmethod
    def _prepare_session(
        identity: VerifiedOidcIdentity,
        *,
        resource: PrivateOidcResourceCredential | None = None,
    ) -> tuple[str, int, str, datetime]:
        now = datetime.now(UTC)
        if resource is not None and (
            not isinstance(resource, PrivateOidcResourceCredential)
            or resource.issuer != identity.issuer
            or resource.subject != identity.subject
            or resource.client_id != identity.client_id
            or resource.expires_at < identity.expires_at
            or resource.expires_at <= now
        ):
            raise OidcSessionStoreUnavailable(
                "resource bearer not bound to current browser identity"
            )
        seconds = min(int((identity.expires_at - now).total_seconds()), _MAX_IDENTITY_SECONDS)
        if seconds < 1:
            raise OidcSessionStoreUnavailable("Rauthy identity already expired")
        ticket = secrets.token_urlsafe(48)
        # The opaque session expires at the earlier of signed ID token expiry
        # and the private Valkey maximum; /session and /me must report the
        # same effective limit as the actual revocable browser cookie.
        expires_at = min(identity.expires_at, now + timedelta(seconds=seconds))
        value = json.dumps(
            {
                "issuer": identity.issuer,
                "subject": identity.subject,
                "client_id": identity.client_id,
                "expires_at": expires_at.isoformat(),
                **(
                    {
                        "resource": {
                            "audience": resource.audience,
                            "bearer": resource.bearer.get_secret_value(),
                            "expires_at": resource.expires_at.isoformat(),
                        }
                    }
                    if resource is not None
                    else {}
                ),
            },
            separators=(",", ":"),
        )
        return ticket, seconds, value, expires_at

    async def create_session(
        self,
        identity: VerifiedOidcIdentity,
        *,
        resource: PrivateOidcResourceCredential | None = None,
    ) -> tuple[str, int]:
        ticket, seconds, value, _deadline = self._prepare_session(identity, resource=resource)
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
        if raw is None or not isinstance(raw, str) or len(raw) > 16384:
            return None
        try:
            item = json.loads(raw, object_pairs_hook=_unique_oidc_fields)
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

    async def get_resource_credential(
        self, ticket: str, *, issuer: str, client_id: str, audience: str
    ) -> PrivateOidcResourceCredential | None:
        """Fetch private escrow only, never treat it as a current effect decision.

        Identity and bearer share ONE revocable Valkey record. Logout cannot
        delete the identity yet leave a separately reusable bearer record.
        """
        validate_files_resource_intent(
            issuer=issuer, client_id=client_id, resource_audience=audience
        )
        try:
            raw = await self._client.get(self._key("session", ticket))
        except ValkeyError:
            raise OidcSessionStoreUnavailable("private resource escrow unavailable") from None
        if not isinstance(raw, str) or len(raw) > 16384:
            return None
        try:
            value = json.loads(raw, object_pairs_hook=_unique_oidc_fields)
            resource = value["resource"]
            expiry = min(
                datetime.fromisoformat(value["expires_at"]),
                datetime.fromisoformat(resource["expires_at"]),
            )
            bearer = resource["bearer"]
            if (
                value["issuer"].rstrip("/") != issuer.rstrip("/")
                or value["client_id"] != client_id
                or resource["audience"] != audience
                or not isinstance(value["subject"], str)
                or not 1 <= len(value["subject"]) <= 256
                or expiry.tzinfo is None
                or expiry <= datetime.now(UTC)
                or not isinstance(bearer, str)
                or not 80 <= len(bearer) <= 8192
                or not bearer.isascii()
                or any(char.isspace() for char in bearer)
            ):
                return None
            return PrivateOidcResourceCredential(
                value["issuer"], value["subject"], client_id, audience, expiry, SecretStr(bearer)
            )
        except (ValueError, TypeError, KeyError, AttributeError):
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
    *,
    test_only_local_origin: str | None = None,
) -> APIRouter:
    public_origin = resolve_browser_origin(
        test_origin=test_only_local_origin,
        provider_issuer=provider.issuer,
        provider_client=provider.client_id,
    )
    callback_uri = public_origin + REGISTERED_RAUTHY_CALLBACK_PATH
    panel_uri = public_origin + "/panel/"
    expected_host = local_browser_host(test_only_local_origin)

    def enforce_test_host(request: Request) -> None:
        if expected_host is not None and request.headers.getlist("host") != [expected_host]:
            raise HTTPException(403, detail="local OIDC browser host mismatch")

    router = APIRouter()

    @router.get(AUTH_API_PREFIX + "/authorize")
    async def start(request: Request) -> Response:
        enforce_test_host(request)
        try:
            attempt = await provider.prepare_authorization_code(redirect_uri=callback_uri)
            await sessions.save_transaction(
                state=attempt.state,
                nonce=attempt.nonce,
                verifier=attempt.code_verifier.get_secret_value(),
                issuer=provider.issuer,
                client_id=provider.client_id,
                resource_audience=attempt.resource_audience,
            )
        except (OidcProviderUnavailable, OidcSessionStoreUnavailable) as exc:
            raise HTTPException(503, detail="OIDC login unavailable") from exc
        response = RedirectResponse(attempt.authorization_url, status_code=302, headers=_NO_STORE)
        _cookie(response, _TX_COOKIE, attempt.state, _MAX_TRANSACTION_SECONDS)
        return response

    @router.get(REGISTERED_RAUTHY_CALLBACK_PATH)
    async def callback(request: Request) -> Response:
        enforce_test_host(request)
        args = request.query_params
        states = args.getlist("state")
        codes = args.getlist("code")
        issuers = args.getlist("iss")
        if (
            set(args) != {"state", "code", "iss"}
            or len(states) != 1
            or len(codes) != 1
            or len(issuers) != 1
            or not 12 <= len(issuers[0]) <= 512
            or any(ch.isspace() for ch in issuers[0])
            or _TOKEN.fullmatch(states[0]) is None
            or not 1 <= len(codes[0]) <= 4096
            or any(ch.isspace() for ch in codes[0])
        ):
            raise HTTPException(400, detail="invalid OIDC authorization callback")
        cookies = _strict_browser_cookies(request)
        original = cookies.get(_TX_COOKIE, "") if cookies is not None else ""
        if _TOKEN.fullmatch(original) is None or not hmac.compare_digest(original, states[0]):
            raise HTTPException(401, detail="OIDC state mismatch")
        try:
            transaction = await sessions.consume_transaction(
                state=states[0],
                issuer=provider.issuer,
                client_id=provider.client_id,
                resource_audience=provider.resource_audience,
            )
            if transaction is None:
                raise HTTPException(401, detail="OIDC state already used or expired")
            login = await provider.authenticate_authorization_code(
                code=codes[0],
                redirect_uri=callback_uri,
                code_verifier=transaction.verifier,
                expected_nonce=transaction.nonce,
                expected_issuer=issuers[0],
                resource_audience=transaction.resource_audience,
            )
            if transaction.expires_at <= datetime.now(UTC):
                raise OidcIdentityRejected("original transaction expired during OAuth exchange")
            ticket, age = await sessions.create_session(login.identity, resource=login.resource)
        except (
            OidcProviderUnavailable,
            OidcIdentityKeysUnavailable,
            OidcSessionStoreUnavailable,
        ) as exc:
            raise HTTPException(503, detail="OIDC identity service unavailable") from exc
        except OidcIdentityRejected as exc:
            raise HTTPException(401, detail="OIDC identity verification failed") from exc
        response = RedirectResponse(panel_uri, status_code=303, headers=_NO_STORE)
        _clear(response, _TX_COOKIE)
        _cookie(response, _SID_COOKIE, ticket, age)
        return response

    @router.get(AUTH_API_PREFIX + "/session")
    async def current_session(request: Request) -> Response:
        enforce_test_host(request)
        cookies = _strict_browser_cookies(request)
        sid = cookies.get(_SID_COOKIE, "") if cookies is not None else ""
        if _TOKEN.fullmatch(sid) is None:
            raise HTTPException(401, detail="OIDC browser session required")
        try:
            identity = await sessions.get_session(sid)
        except OidcSessionStoreUnavailable as exc:
            raise HTTPException(503, detail="OIDC session store unavailable") from exc
        if identity is None:
            raise HTTPException(401, detail="OIDC browser session expired")
        # An opaque Valkey ticket from an older issuer/client deployment
        # is NOT authenticated for the newly configured Rauthy realm.
        if (
            identity.issuer.rstrip("/") != provider.issuer
            or identity.client_id != provider.client_id
        ):
            # Remove the stale Valkey ticket rather than merely denying it:
            # an issuer/client rollback must not reactivate the old session.
            try:
                await sessions.delete_session(sid)
            except OidcSessionStoreUnavailable as exc:
                raise HTTPException(503, detail="OIDC stale ticket could not be revoked") from exc
            response = JSONResponse(
                {"detail": "OIDC browser realm no longer current"},
                status_code=401,
                headers=_NO_STORE,
            )
            _clear(response, _SID_COOKIE)
            return response
        # Rauthy identity alone never grants Platform or MCP permissions.
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

    @router.post(AUTH_API_PREFIX + "/logout")
    async def logout(request: Request) -> Response:
        enforce_test_host(request)
        if request.headers.getlist("origin") != [public_origin]:
            raise HTTPException(403, detail="same-origin logout required")
        cookies = _strict_browser_cookies(request)
        if cookies is None:
            raise HTTPException(401, detail="ambiguous OIDC browser cookies")
        sid = cookies.get(_SID_COOKIE, "")
        native_state = cookies.get(_NATIVE_TX_COOKIE, "")
        if _TOKEN.fullmatch(native_state) is not None:
            try:
                await sessions.delete_native_init(state=native_state)
            except OidcSessionStoreUnavailable as exc:
                raise HTTPException(503, detail="native Init logout not confirmed") from exc
        if _TOKEN.fullmatch(sid) is not None:
            try:
                await sessions.delete_session(sid)
            except OidcSessionStoreUnavailable as exc:
                raise HTTPException(503, detail="OIDC logout not confirmed") from exc
        response = Response(status_code=204, headers=_NO_STORE)
        _clear(response, _SID_COOKIE)
        _clear(response, _TX_COOKIE)
        _clear(response, _NATIVE_TX_COOKIE)
        return response

    return router
