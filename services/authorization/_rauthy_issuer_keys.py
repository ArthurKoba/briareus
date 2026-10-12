"""Bounded, fail-closed public Rauthy OIDC discovery and signing-key refresh.

The HTTPS issuer is an independently reviewed deployment input, never taken
from an unverified bearer header, request URL or a public JWT claim.
"""

from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Callable
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from authorization._rauthy_jwks import RauthyJwksVerifier, RauthyKeysUnavailable


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        raise RauthyKeysUnavailable("Rauthy issuer must not redirect key fetches")


def _read_json_https(url: str, *, max_bytes: int) -> dict[str, object]:
    # Uses platform CA verification and does not forward headers/cookies/tokens.
    client = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with client.open(request, timeout=5.0) as response:
            if response.status != 200:
                raise RauthyKeysUnavailable("Rauthy issuer returned non-success")
            mime = response.headers.get_content_type()
            if mime not in {"application/json", "application/jwk-set+json"}:
                raise RauthyKeysUnavailable("Rauthy keys response is not JSON")
            payload = response.read(max_bytes + 1)
    except (OSError, URLError, HTTPError, ValueError) as exc:
        raise RauthyKeysUnavailable("Rauthy issuer HTTPS fetch unavailable") from exc
    if len(payload) > max_bytes:
        raise RauthyKeysUnavailable("Rauthy issuer response exceeded byte limit")
    try:
        content: Any = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise RauthyKeysUnavailable("Rauthy issuer returned invalid JSON") from exc
    if not isinstance(content, dict):
        raise RauthyKeysUnavailable("Rauthy issuer must return a JSON object")
    return content


def _trusted_jwks_url(issuer: str, metadata: dict[str, object]) -> str:
    if metadata.get("issuer") != issuer:
        raise RauthyKeysUnavailable("Rauthy metadata issuer mismatch")
    uri = metadata.get("jwks_uri")
    if not isinstance(uri, str):
        raise RauthyKeysUnavailable("Rauthy signing-key URI absent")
    expected = urlsplit(issuer)
    actual = urlsplit(uri)
    if (
        actual.scheme != "https"
        or actual.netloc != expected.netloc
        or actual.username is not None
        or actual.password is not None
        or actual.query
        or actual.fragment
        or not actual.path.startswith(expected.path)
        or actual.path == expected.path
    ):
        raise RauthyKeysUnavailable("Rauthy signing-key URI outside trusted issuer")
    return uri


class TrustedRauthyIssuerKeys:
    """Refresh verified key material on a bounded TTL; expire closed on outage.

    The refresh data source is fixed to an operator-approved HTTPS issuer.
    Key rotation can update a verified JWKS only after matching discovery.
    No JWKS document/URL from an incoming JWT is ever fetched.
    """

    def __init__(
        self,
        *,
        issuer: str,
        resource_audience: str,
        oauth_client_id: str,
        ttl_seconds: float = 300.0,
        json_fetch: Callable[[str, int], dict[str, object]] | None = None,
    ) -> None:
        parsed = urlsplit(issuer)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not issuer.endswith("/")
            or not 1 <= ttl_seconds <= 900
        ):
            raise ValueError("exact trusted HTTPS issuer and bounded refresh TTL required")
        self._issuer = issuer
        self._audience = resource_audience
        self._client_id = oauth_client_id
        self._ttl_seconds = ttl_seconds
        self._fetch = json_fetch
        self._expires = 0.0
        self._current: RauthyJwksVerifier | None = None
        self._lock = asyncio.Lock()

    def _fetch_document(self, url: str, maximum: int) -> dict[str, object]:
        if self._fetch is not None:
            return self._fetch(url, maximum)
        return _read_json_https(url, max_bytes=maximum)

    def _load(self) -> RauthyJwksVerifier:
        discovery = self._fetch_document(self._issuer + ".well-known/openid-configuration", 16384)
        uri = _trusted_jwks_url(self._issuer, discovery)
        keys = self._fetch_document(uri, 65536)
        return RauthyJwksVerifier(
            issuer=self._issuer,
            resource_audience=self._audience,
            oauth_client_id=self._client_id,
            trusted_jwks=keys,
        )

    async def get_verifier(self) -> RauthyJwksVerifier:
        now = monotonic()
        if self._current is not None and now < self._expires:
            return self._current
        async with self._lock:
            if self._current is not None and monotonic() < self._expires:
                return self._current
            # Do not serve a stale signing key or Permit after a failed
            # provider refresh, even if a prior cache entry was valid.
            self._current = None
            self._expires = 0
            current = await asyncio.to_thread(self._load)
            self._current = current
            self._expires = monotonic() + self._ttl_seconds
            return current
