"""Native first factor with cancelable one-time state and real PKCE completion.

No provider credential, cookie, CSRF, MFA code or access bearer is returned.
Unsupported provider continuation states explicitly remain unauthenticated.
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ._api_paths import AUTH_API_PREFIX, REGISTERED_RAUTHY_CALLBACK_PATH
from ._native_credentials import NativeFirstFactorRequest
from ._oidc import OidcProviderUnavailable, RauthyOidcAdapter, _unique_oidc_fields
from ._oidc_browser import (
    _NATIVE_TX_COOKIE,
    _SID_COOKIE,
    OidcBrowserSessionStore,
    OidcSessionStoreUnavailable,
    PrivateNativePending,
    _clear,
    _cookie,
    _strict_browser_cookies,
)
from ._oidc_id_token import OidcIdentityKeysUnavailable, OidcIdentityRejected
from ._oidc_origin_policy import PUBLIC_ORIGIN, local_browser_host, resolve_browser_origin
from ._rauthy_native_init import PinnedNativeRauthyInit
from ._rauthy_native_protocol import NativeProviderProtocolUnavailable, PrivateNativeLoginStep

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_UNSUPPORTED = frozenset(
    {
        "otp_pending",
        "webauthn_pending",
        "tos_pending",
        "account_update_required",
        "client_mfa_required",
    }
)


def _failure(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status, headers=_NO_STORE)


def native_login_router(
    *,
    provider: RauthyOidcAdapter,
    transactions: OidcBrowserSessionStore,
    native_provider: PinnedNativeRauthyInit,
    test_only_local_origin: str | None,
) -> APIRouter:
    origin = resolve_browser_origin(
        test_origin=test_only_local_origin,
        provider_issuer=provider.issuer,
        provider_client=provider.client_id,
    )
    host = local_browser_host(test_only_local_origin) or "briareus.koba-nexus.ru"
    if (
        native_provider.issuer != provider.issuer
        or native_provider.client_id != provider.client_id
        or native_provider.callback != origin + REGISTERED_RAUTHY_CALLBACK_PATH
        or (test_only_local_origin is None and origin != PUBLIC_ORIGIN)
    ):
        raise ValueError("native credentials require one fixed matching issuer/client/callback")
    router = APIRouter()

    async def read_body(request: Request, *, empty: bool) -> bytes | JSONResponse:
        if (
            request.headers.getlist("origin") != [origin]
            or request.headers.getlist("host") != [host]
            or request.headers.getlist("content-type") != ["application/json"]
            or request.headers.getlist("authorization")
            or request.headers.getlist("transfer-encoding")
            or len(request.headers.getlist("cookie")) > 1
            or request.query_params
        ):
            return _failure(403, "NATIVE_ORIGIN_OR_REQUEST_DENIED")
        lengths = request.headers.getlist("content-length")
        if (
            len(lengths) != 1
            or not 1 <= len(lengths[0]) <= 4
            or not lengths[0].isascii()
            or not lengths[0].isdecimal()
            or not 2 <= int(lengths[0]) <= 8192
        ):
            return _failure(422, "NATIVE_REQUEST_INVALID")
        content = bytearray()
        try:
            async with asyncio.timeout(5):
                async for block in request.stream():
                    if len(content) + len(block) > 8192:
                        return _failure(422, "NATIVE_REQUEST_INVALID")
                    content.extend(block)
        except (TimeoutError, RuntimeError):
            return _failure(422, "NATIVE_REQUEST_INVALID")
        if len(content) != int(lengths[0]) or (empty and bytes(content) != b"{}"):
            return _failure(422, "NATIVE_REQUEST_INVALID")
        return bytes(content)

    async def retire(state: str) -> bool:
        # Drain bounded cleanup even if downstream cancellation repeats.
        async def remove() -> None:
            async with asyncio.timeout(4):
                await transactions.delete_native_init(state=state)

        task = asyncio.create_task(remove())
        interrupted = False
        try:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    interrupted = True
            task.result()
        except (OidcSessionStoreUnavailable, TimeoutError):
            if interrupted:
                raise asyncio.CancelledError from None
            return False
        if interrupted:
            raise asyncio.CancelledError
        return True

    @router.get(AUTH_API_PREFIX + "/capabilities")
    async def capabilities(request: Request) -> Response:
        if request.headers.getlist("host") != [host] or request.query_params:
            return _failure(403, "NATIVE_ORIGIN_OR_REQUEST_DENIED")
        # Configured API capability only, not provider health or a signed User.
        return JSONResponse(
            {
                "protocol": "rauthy-native-v1",
                "first_factor": "password",
                "pow": "client-solved",
                "cancel": True,
                "continuations": [],
            },
            headers=_NO_STORE,
        )

    @router.post(AUTH_API_PREFIX + "/cancel")
    async def cancel(request: Request) -> Response:
        body = await read_body(request, empty=True)
        if isinstance(body, JSONResponse):
            return body
        handles = _strict_browser_cookies(request)
        if handles is None:
            return _failure(401, "NATIVE_COOKIE_INVALID")
        state = handles.get(_NATIVE_TX_COOKIE)
        if state is not None and not await retire(state):
            return _failure(503, "NATIVE_CANCEL_UNAVAILABLE")
        response = Response(status_code=204, headers=_NO_STORE)
        _clear(response, _NATIVE_TX_COOKIE)
        return response

    async def finish(
        request: Request, pending: PrivateNativePending, step: PrivateNativeLoginStep
    ) -> Response:
        if step.state in _UNSUPPORTED:
            return JSONResponse(
                {
                    "stage": step.state,
                    "authenticated": False,
                    "continuation_available": False,
                    "restart_required": True,
                },
                status_code=409,
                headers=_NO_STORE,
            )
        if step.state == "rate_limited":
            return JSONResponse(
                {
                    "error": {"code": "NATIVE_RATE_LIMITED"},
                    "retry_not_before": step.retry_not_before,
                },
                status_code=429,
                headers=_NO_STORE,
            )
        if step.state in {"credentials_rejected", "request_rejected"}:
            return _failure(401, "NATIVE_CREDENTIALS_REJECTED")
        if step.state != "oauth_callback_pending" or step.secret is None:
            raise NativeProviderProtocolUnavailable("native step cannot finish login")
        # The pinned decoder already verified exact callback/code/state/iss.
        args = parse_qs(urlsplit(step.secret.get_secret_value()).query, strict_parsing=True)
        login = await provider.authenticate_authorization_code(
            code=args["code"][0],
            redirect_uri=origin + REGISTERED_RAUTHY_CALLBACK_PATH,
            code_verifier=pending.verifier,
            expected_nonce=pending.nonce,
            expected_issuer=args["iss"][0],
            resource_audience=pending.resource_audience,
        )
        if await request.is_disconnected():
            return _failure(401, "NATIVE_ATTEMPT_DISCONNECTED")
        committed = await transactions.complete_native_login(
            pending=pending, identity=login.identity, resource=login.resource
        )
        if committed is None:
            return _failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED")
        ticket, seconds = committed
        if await transactions.get_session(ticket) is None or await request.is_disconnected():
            return _failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED")
        response = JSONResponse(
            {
                "stage": "authenticated",
                "authenticated": True,
                "authority": "rauthy",
                "platform_membership_verified": False,
                "permissions": [],
            },
            headers=_NO_STORE,
        )
        _cookie(response, _SID_COOKIE, ticket, seconds)
        # Retain the existing attempt cookie until its natural short expiry:
        # a concurrent cancel/logout can still invalidate a late cookie reply.
        return response

    @router.post(AUTH_API_PREFIX + "/first-factor")
    async def first_factor(request: Request) -> Response:
        body = await read_body(request, empty=False)
        if isinstance(body, JSONResponse):
            return body
        try:
            credentials = NativeFirstFactorRequest.model_validate(
                json.loads(body, object_pairs_hook=_unique_oidc_fields)
            )
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return _failure(422, "NATIVE_REQUEST_INVALID")
        del body
        handles = _strict_browser_cookies(request)
        if handles is None:
            return _failure(401, "NATIVE_COOKIE_INVALID")
        state = handles.get(_NATIVE_TX_COOKIE)
        if state is None:
            return _failure(401, "NATIVE_INIT_REQUIRED")
        claimed = False
        success = False
        response: Response
        try:
            async with asyncio.timeout(30):
                pending = await transactions.consume_native_init(
                    state=state, issuer=provider.issuer, client_id=provider.client_id
                )
                if pending is None:
                    # Losing consumers must not cancel the winning request.
                    return _failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CLAIMED")
                claimed = True
                if (
                    pending.resource_audience != provider.resource_audience
                    or not await transactions.native_claim_is_current(pending)
                    or await request.is_disconnected()
                ):
                    response = _failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED")
                else:
                    step = await native_provider.authorize(pending=pending, credentials=credentials)
                    if (
                        not await transactions.native_claim_is_current(pending)
                        or await request.is_disconnected()
                    ):
                        response = _failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED")
                    else:
                        response = await finish(request, pending, step)
                        success = response.status_code == 200
        except asyncio.CancelledError:
            await retire(state)
            raise
        except OidcIdentityRejected:
            response = _failure(401, "NATIVE_IDENTITY_REJECTED")
        except (
            OidcProviderUnavailable,
            OidcIdentityKeysUnavailable,
            OidcSessionStoreUnavailable,
            NativeProviderProtocolUnavailable,
            TimeoutError,
        ):
            # A timed-out claim may have committed before its reply was lost.
            claimed = True
            response = _failure(503, "NATIVE_LOGIN_UNAVAILABLE")
        if claimed and not success and not await retire(state):
            return _failure(503, "NATIVE_CANCEL_UNAVAILABLE")
        return response

    return router
