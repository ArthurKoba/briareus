"""Pinned Rauthy v0.37.1 Init/PoW/first-factor transport; no local issuer.

Only an explicitly pinned native provider may initialize the first factor.
The provider cookie/CSRF stay in the Backend-only Valkey transaction and
MUST NEVER be sent to the browser or a shared/cross-user HTTP client.
"""

from __future__ import annotations

import ssl
from datetime import UTC, datetime

import httpx

from ._api_paths import REGISTERED_RAUTHY_CALLBACK_PATH
from ._native_credentials import NativeFirstFactorRequest
from ._oidc import _pkce_s256
from ._oidc_browser import PrivateNativePending
from ._oidc_origin_policy import (
    LOCAL_RAUTHY_CLIENT,
    LOCAL_RAUTHY_ISSUER,
    LOCAL_TEST_ORIGIN,
    PUBLIC_ORIGIN,
)
from ._rauthy_native_protocol import (
    NativeProviderProtocolUnavailable,
    PrivateNativeInitSession,
    PrivateNativeLoginStep,
    interpret_native_authorize,
    parse_native_session_init,
)


async def _bounded_native_reply(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    limit: int,
) -> tuple[int, httpx.Headers, bytes]:
    """Observe an upstream reply without eagerly buffering unbounded bytes."""
    async with client.stream("POST", url, headers=headers) as response:
        result = bytearray()
        async for part in response.aiter_bytes():
            if len(part) > limit - len(result):
                raise NativeProviderProtocolUnavailable("native Rauthy response exceeds bound")
            result.extend(part)
        return response.status_code, response.headers, bytes(result)


class PinnedNativeRauthyInit:
    """Two fixed HTTPS Rauthy realms, no caller-controlled remote address."""

    def __init__(
        self, *, local_rauthy_cert_pem: str | None = None, public_dev: bool = False
    ) -> None:
        if public_dev:
            if local_rauthy_cert_pem is not None:
                raise ValueError("public Rauthy cannot use caller-supplied local trust")
            self._tls = ssl.create_default_context()
            self.issuer = PUBLIC_ORIGIN + "/auth/v1"
            self.client_id = "briareus-control-panel"
            self.callback = PUBLIC_ORIGIN + REGISTERED_RAUTHY_CALLBACK_PATH
            return
        if (
            not isinstance(local_rauthy_cert_pem, str)
            or not 256 <= len(local_rauthy_cert_pem) <= 8192
            or "-----BEGIN CERTIFICATE-----" not in local_rauthy_cert_pem
            or "-----BEGIN PRIVATE KEY-----" in local_rauthy_cert_pem
        ):
            raise ValueError("pinned native local Rauthy certificate required")
        try:
            self._tls = ssl.create_default_context(cadata=local_rauthy_cert_pem)
        except (ssl.SSLError, ValueError):
            raise ValueError("untrusted local native Rauthy TLS") from None
        self.issuer = LOCAL_RAUTHY_ISSUER
        self.client_id = LOCAL_RAUTHY_CLIENT
        self.callback = LOCAL_TEST_ORIGIN + REGISTERED_RAUTHY_CALLBACK_PATH

    @classmethod
    def for_public_dev(cls) -> PinnedNativeRauthyInit:
        """Explicit source-only opt-in to a system-CA-validated HTTPS issuer.

        No client/resource registration or authorization is created here.
        """
        return cls(public_dev=True)

    async def initialize(self) -> PrivateNativeInitSession:
        # Fresh per-attempt client means Rauthy sessions can never accidentally
        # bleed between concurrent human logins via a global CookieJar.
        try:
            async with httpx.AsyncClient(
                verify=self._tls,
                trust_env=False,
                follow_redirects=False,
                timeout=5.0,
            ) as client:
                status, headers, body = await _bounded_native_reply(
                    client,
                    self.issuer + "/oidc/session",
                    headers={"Accept": "application/json"},
                    limit=8192,
                )
                return parse_native_session_init(
                    status_code=status,
                    content_type=headers.get("content-type", ""),
                    body=body,
                    set_cookie_headers=tuple(headers.get_list("set-cookie")),
                )
        except httpx.HTTPError:
            raise NativeProviderProtocolUnavailable(
                "native Rauthy Init provider unavailable"
            ) from None

    async def issue_pow(self) -> str:
        """Get one official provider challenge; only upstream validates its solution."""
        try:
            async with httpx.AsyncClient(
                verify=self._tls,
                trust_env=False,
                follow_redirects=False,
                timeout=5.0,
            ) as client:
                status, _headers, body = await _bounded_native_reply(
                    client,
                    self.issuer + "/pow",
                    headers={"Accept": "text/plain"},
                    limit=128,
                )
                if status != 200 or not 2 <= len(body) <= 128:
                    raise NativeProviderProtocolUnavailable("Rauthy PoW unavailable")
                challenge = body.decode("ascii")
                if any(ord(c) <= 32 or ord(c) > 126 for c in challenge) or not challenge:
                    raise NativeProviderProtocolUnavailable("Rauthy PoW malformed")
                return challenge
        except (httpx.HTTPError, UnicodeError):
            raise NativeProviderProtocolUnavailable("Rauthy PoW connection unavailable") from None

    async def authorize(
        self, *, pending: PrivateNativePending, credentials: NativeFirstFactorRequest
    ) -> PrivateNativeLoginStep:
        """Use the official provider's first factor, never the password OAuth grant.

        A fresh client, fixed URL and original server-held cookie/CSRF isolate
        attempts. All success still needs signed code/PKCE/Userinfo validation.
        Provider Set-Cookie/MFA secrets never reach the public browser.
        """
        if (
            pending.issuer != self.issuer
            or pending.client_id != self.client_id
            or pending.expires_at <= datetime.now(UTC)
        ):
            raise NativeProviderProtocolUnavailable("native original realm expired or mismatched")
        callback = self.callback
        payload = {
            "email": credentials.email.get_secret_value(),
            "password": credentials.password.get_secret_value(),
            "pow": credentials.pow.get_secret_value(),
            "client_id": pending.client_id,
            "redirect_uri": callback,
            "scopes": ["openid", "profile", "email"],
            "state": pending.state,
            "nonce": pending.nonce,
            "code_challenge": _pkce_s256(pending.verifier.get_secret_value()),
            "code_challenge_method": "S256",
            **({"resource": pending.resource_audience} if pending.resource_audience else {}),
        }
        began = datetime.now(UTC)
        try:
            async with (
                httpx.AsyncClient(
                    verify=self._tls,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=10.0,
                ) as client,
                client.stream(
                    "POST",
                    self.issuer + "/oidc/authorize",
                    json=payload,
                    headers={
                        "Accept": "application/json",
                        "X-CSRF-Token": pending.csrf.get_secret_value(),
                        "Cookie": pending.provider_cookie.get_secret_value(),
                    },
                ) as response,
            ):
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > 8192:
                        raise NativeProviderProtocolUnavailable("native provider reply too large")
                    body.extend(chunk)
                if any(
                    len(response.headers.get_list(name)) > 1
                    for name in (
                        "location",
                        "content-type",
                        "x-csrf-token",
                        "x-retry-not-before",
                    )
                ):
                    raise NativeProviderProtocolUnavailable("ambiguous native response headers")
                if (
                    response.status_code in (200, 206)
                    and response.headers.get("content-type", "").split(";", 1)[0]
                    != "application/json"
                ):
                    raise NativeProviderProtocolUnavailable("native challenge media type invalid")
                return interpret_native_authorize(
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    body=bytes(body),
                    expected_callback=callback,
                    expected_state=pending.state,
                    expected_issuer=self.issuer + "/",
                    now=began,
                )
        except (httpx.HTTPError, UnicodeError, ValueError):
            raise NativeProviderProtocolUnavailable(
                "native first-factor provider unavailable"
            ) from None
        finally:
            payload.clear()
