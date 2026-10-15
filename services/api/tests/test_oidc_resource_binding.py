"""Resource-bound OAuth code flow with actual signatures and explicit IdP fixtures."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import unittest
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import jwt
from control_panel_api._oidc import RauthyOidcAdapter
from control_panel_api._oidc_browser import (
    _SID_COOKIE,
    _TX_COOKIE,
    OidcBrowserSessionStore,
    oidc_browser_router,
)
from control_panel_api._oidc_native_start import native_login_start_router
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response
from pydantic import SecretStr
from test_native_pow import AsyncValkeyStub, LocalRauthyInit

_ISSUER = "https://localhost:18444/auth/v1/"
_ORIGIN = "https://127.0.0.1:18446"
_CLIENT = "briareus-local-panel"
_RESOURCE = _ORIGIN + "/hands/files/mcp"
_SUBJECT = "A" * 24


class ProviderFixture:
    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        self.jwk.update(kid="source-fixture", use="sig", alg="RS256")
        self.nonce = ""
        self.challenge = ""
        self.access_changes: dict[str, object] = {}
        self.access_bearer = ""
        self.id_bearer = ""
        self.exchanges = 0
        self.subject = _SUBJECT
        self.userinfo_wait = 0.0
        self.expires_in = 90
        self.scoped = True
        self.duplicate_response = False
        self.reject_target = False

    def sign(self, claims: dict[str, object]) -> str:
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "source-fixture"})

    async def __call__(self, request: Request) -> Response:
        assert str(request.url).startswith(_ISSUER)
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return Response(
                200,
                json={
                    "issuer": _ISSUER,
                    "authorization_endpoint": _ISSUER + "oidc/authorize",
                    "token_endpoint": _ISSUER + "oidc/token",
                    "jwks_uri": _ISSUER + "oidc/certs",
                    "userinfo_endpoint": _ISSUER + "oidc/userinfo",
                    "code_challenge_methods_supported": ["S256"],
                    "response_types_supported": ["code"],
                },
            )
        if path.endswith("/oidc/certs"):
            return Response(200, json={"keys": [self.jwk]})
        if path.endswith("/oidc/token"):
            form = parse_qs(request.content.decode())
            self.exchanges += 1
            assert form.get("resource") == ([_RESOURCE] if self.scoped else None)
            assert form["client_id"] == [_CLIENT]
            assert form["redirect_uri"] == [_ORIGIN + "/api/auth/oidc/callback"]
            verifier = form["code_verifier"][0]
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .rstrip(b"=")
                .decode()
            )
            assert challenge == self.challenge
            if self.reject_target:
                return Response(400, json={"error": "invalid_target"})
            now = int(datetime.now(UTC).timestamp())
            identity = {
                "iss": _ISSUER,
                "sub": _SUBJECT,
                "aud": _CLIENT,
                "azp": _CLIENT,
                "typ": "Id",
                "iat": now,
                "nbf": now,
                "exp": now + 120,
                "nonce": self.nonce,
            }
            access = {
                "iss": _ISSUER,
                "sub": _SUBJECT,
                "aud": [_CLIENT, _RESOURCE] if self.scoped else _CLIENT,
                "azp": _CLIENT,
                "typ": "Bearer",
                "iat": now,
                "nbf": now,
                "exp": now + 60,
                "jti": "fixture-jti",
            }
            access.update(self.access_changes)
            self.id_bearer, self.access_bearer = self.sign(identity), self.sign(access)
            payload = {
                "id_token": self.id_bearer,
                "access_token": self.access_bearer,
                "expires_in": self.expires_in,
                "token_type": "Bearer",
            }
            if self.duplicate_response:
                raw = json.dumps(payload)[:-1] + ',"expires_in":999}'
                return Response(200, content=raw, headers={"content-type": "application/json"})
            return Response(200, json=payload)
        if path.endswith("/oidc/userinfo"):
            assert request.headers["authorization"] == "Bearer " + self.access_bearer
            if self.userinfo_wait:
                await asyncio.sleep(self.userinfo_wait)
            return Response(200, json={"sub": self.subject, "id": self.subject})
        raise AssertionError("unapproved fixture endpoint")


class ResourceBindingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fixture = ProviderFixture()
        self.http = AsyncClient(transport=MockTransport(self.fixture), follow_redirects=False)
        self.provider = RauthyOidcAdapter(
            issuer=_ISSUER, client_id=_CLIENT, http_client=self.http, resource_audience=_RESOURCE
        )
        self.memory = AsyncValkeyStub()
        self.store = OidcBrowserSessionStore(password=SecretStr("f" * 64), client=self.memory)
        app = FastAPI()
        app.include_router(
            oidc_browser_router(self.provider, self.store, test_only_local_origin=_ORIGIN)
        )
        self.public = AsyncClient(
            transport=ASGITransport(app=app), base_url=_ORIGIN, follow_redirects=False
        )

    async def asyncTearDown(self) -> None:
        await self.public.aclose()
        await self.http.aclose()

    async def start(self) -> dict[str, list[str]]:
        response = await self.public.get("/api/v1/auth/authorize")
        self.assertEqual(response.status_code, 302, response.text)
        params = parse_qs(urlsplit(response.headers["location"]).query)
        self.assertEqual(params["resource"], [_RESOURCE])
        self.fixture.nonce = params["nonce"][0]
        self.fixture.challenge = params["code_challenge"][0]
        return params

    async def finish(self, args: dict[str, list[str]]) -> Response:
        return await self.public.get(
            "/api/auth/oidc/callback",
            params={"code": "K" * 64, "state": args["state"][0], "iss": _ISSUER},
        )

    async def test_complete_original_code_binding_and_joint_logout(self) -> None:
        args = await self.start()
        response = await self.finish(args)
        self.assertEqual(response.status_code, 303, response.text)
        sid = self.public.cookies.get(_SID_COOKIE)
        credential = await self.store.get_resource_credential(
            sid, issuer=_ISSUER, client_id=_CLIENT, audience=_RESOURCE
        )
        self.assertEqual(credential.bearer.get_secret_value(), self.fixture.access_bearer)
        self.assertLessEqual(credential.expires_at, datetime.now(UTC) + timedelta(seconds=60))
        self.assertNotIn(self.fixture.access_bearer, repr(credential))
        public = await self.public.get("/api/v1/auth/session")
        self.assertEqual(public.status_code, 200)
        for secret in (self.fixture.access_bearer, self.fixture.id_bearer):
            self.assertNotIn(secret, public.text + str(response.headers))
        self.assertEqual(public.json()["permissions"], [])
        self.public.cookies.set(_TX_COOKIE, args["state"][0])
        repeated = await self.finish(args)
        self.assertEqual(repeated.status_code, 401)
        self.assertEqual(self.fixture.exchanges, 1)
        logout = await self.public.post("/api/v1/auth/logout", headers={"Origin": _ORIGIN})
        self.assertEqual(logout.status_code, 204)
        self.assertIsNone(
            await self.store.get_resource_credential(
                sid, issuer=_ISSUER, client_id=_CLIENT, audience=_RESOURCE
            )
        )
        self.assertIsNone(await self.store.get_session(sid))

    async def test_wrong_resource_purpose_subject_or_extra_audience_never_mints_cookie(
        self,
    ) -> None:
        for change in (
            {"aud": _CLIENT},
            {"aud": [_CLIENT, _RESOURCE + "/"]},
            {"aud": [_CLIENT, _RESOURCE, "https://other.invalid/mcp"]},
            {"aud": [_RESOURCE, _RESOURCE]},
            {"aud": [_RESOURCE, 1]},
            {"typ": "Id"},
            {"typ": "DPoP"},
            {"azp": "wrong-client"},
            {"sub": "B" * 24},
            {"exp": True},
            {"iat": "123"},
            {"jti": ""},
            {"act": {"sub": "delegated"}},
            {"cnf": {"jkt": "proof"}},
        ):
            self.fixture.access_changes = change
            response = await self.finish(await self.start())
            self.assertEqual(response.status_code, 401, change)
            self.assertIsNone(self.public.cookies.get(_SID_COOKIE))
            self.assertFalse(any(":session:" in key for key in self.memory.values))

    async def test_unscoped_login_retains_identity_only_compatibility(self) -> None:
        provider = RauthyOidcAdapter(issuer=_ISSUER, client_id=_CLIENT, http_client=self.http)
        self.fixture.scoped = False
        app = FastAPI()
        app.include_router(
            oidc_browser_router(provider, self.store, test_only_local_origin=_ORIGIN)
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=_ORIGIN, follow_redirects=False
        ) as client:
            started = await client.get("/api/v1/auth/authorize")
            args = parse_qs(urlsplit(started.headers["location"]).query)
            self.assertNotIn("resource", args)
            self.fixture.nonce = args["nonce"][0]
            self.fixture.challenge = args["code_challenge"][0]
            result = await client.get(
                "/api/auth/oidc/callback",
                params={
                    "code": "K" * 64,
                    "state": args["state"][0],
                    "iss": _ISSUER,
                },
            )
            self.assertEqual(result.status_code, 303, result.text)
            sid = client.cookies.get(_SID_COOKIE)
            identity = await self.store.get_session(sid)
            self.assertEqual(identity.subject, _SUBJECT)
            self.assertIsNone(
                await self.store.get_resource_credential(
                    sid,
                    issuer=_ISSUER,
                    client_id=_CLIENT,
                    audience=_RESOURCE,
                )
            )
            self.assertNotIn(
                "resource", json.loads(self.memory.values[self.store._key("session", sid)])
            )

    async def test_mismatched_transaction_intent_is_burned_before_exchange(self) -> None:
        args = await self.start()
        key = self.store._key("transaction", args["state"][0])
        record = json.loads(self.memory.values[key])
        record["resource_audience"] = None
        self.memory.values[key] = json.dumps(record)
        self.assertEqual((await self.finish(args)).status_code, 401)
        self.assertNotIn(key, self.memory.values)
        self.assertEqual(self.fixture.exchanges, 0)

    async def test_duplicate_token_fields_and_missing_provider_resource_registration_deny(
        self,
    ) -> None:
        self.fixture.duplicate_response = True
        self.assertEqual((await self.finish(await self.start())).status_code, 503)
        self.fixture.duplicate_response = False
        self.fixture.reject_target = True
        self.assertEqual((await self.finish(await self.start())).status_code, 503)
        self.assertIsNone(self.public.cookies.get(_SID_COOKIE))

    async def test_slow_userinfo_cannot_renew_original_expires_in(self) -> None:
        self.fixture.expires_in = 1
        self.fixture.userinfo_wait = 1.02
        response = await self.finish(await self.start())
        self.assertEqual(response.status_code, 401, response.text)
        self.assertIsNone(self.public.cookies.get(_SID_COOKIE))

    async def test_native_claim_retains_original_resource_and_absolute_expiry(self) -> None:
        attempt = await self.provider.prepare_authorization_code(
            redirect_uri=_ORIGIN + "/api/auth/oidc/callback"
        )
        await self.store.save_native_init(
            state=attempt.state,
            nonce=attempt.nonce,
            verifier=attempt.code_verifier.get_secret_value(),
            issuer=self.provider.issuer,
            client_id=_CLIENT,
            csrf=SecretStr("C" * 32),
            provider_cookie=SecretStr("__Host-RauthySession=" + "X" * 90),
            seconds=60,
            resource_audience=attempt.resource_audience,
        )
        self.assertTrue(
            await self.store.reserve_native_pow(
                state=attempt.state, issuer=self.provider.issuer, client_id=_CLIENT
            )
        )
        self.assertTrue(
            await self.store.confirm_native_pow(
                state=attempt.state, issuer=self.provider.issuer, client_id=_CLIENT
            )
        )
        claim = await self.store.consume_native_init(
            state=attempt.state, issuer=self.provider.issuer, client_id=_CLIENT
        )
        self.assertEqual(claim.resource_audience, _RESOURCE)
        self.assertLessEqual(claim.expires_at, datetime.now(UTC) + timedelta(seconds=60))
        self.assertIsNone(
            await self.store.consume_native_init(
                state=attempt.state, issuer=self.provider.issuer, client_id=_CLIENT
            )
        )

    async def test_native_start_route_preserves_resource_intent_before_first_factor(self) -> None:
        app = FastAPI()
        app.include_router(
            native_login_start_router(
                provider=self.provider,
                transactions=self.store,
                native_init=LocalRauthyInit(),
                test_only_local_origin=_ORIGIN,
            )
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url=_ORIGIN) as client:
            started = await client.post(
                "/api/v1/auth/start",
                content=b"{}",
                headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            )
            self.assertEqual(started.status_code, 201, started.text)
            self.assertIs(started.json()["authenticated"], False)
            state = client.cookies.get("__Host-briareus_native_transaction")
            record = json.loads(self.memory.values[self.store._key("native-init", state)])
            self.assertEqual(record["resource_audience"], _RESOURCE)
            self.assertEqual(record["issuer"], self.provider.issuer)
            self.assertNotIn(record["provider_cookie"], started.text)

    def test_resource_config_cannot_cross_realms_or_accept_arbitrary_urls(self) -> None:
        for resource in (
            _RESOURCE + "/",
            "https://briareus.koba-nexus.ru/hands/files/mcp",
            _ORIGIN + "/hands/terminal/mcp",
            "http://localhost/files",
        ):
            with self.assertRaises(ValueError):
                RauthyOidcAdapter(
                    issuer=_ISSUER,
                    client_id=_CLIENT,
                    http_client=self.http,
                    resource_audience=resource,
                )
