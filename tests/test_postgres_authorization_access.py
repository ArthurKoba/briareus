from __future__ import annotations

import base64
import hashlib
import os
import time
import unittest
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from starlette.applications import Starlette
from starlette.routing import Mount

from authorization.access.api import build_access_app
from authorization.access.control import AccessControl
from authorization.access.database import AccessDatabase
from authorization.access.repository import AccessRepository
from authorization.api import build_authorization_app
from authorization.database import AuthorizationDatabase
from authorization.provider import LocalOAuthProvider
from authorization.repository import AuthorizationRepository
from common.access_contracts import (
    AdminResolveRequest,
    AdminSessionUpdate,
    FullAccessRequest,
    OAuthContext,
    SessionOpenRequest,
    SessionValidateRequest,
)
from common.cache import SharedCache
from common.mcp_surfaces import surface_id
from common.settings import AuthorizationServiceSettings, ValkeySettings

_POSTGRES_HOST = os.getenv("TEST_POSTGRES_HOST", "")
_RUN = bool(_POSTGRES_HOST)


def _signing_key_value() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    der = key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return base64.b64encode(der).decode()


@unittest.skipUnless(_RUN, "integration PostgreSQL is not configured")
class PostgresAuthorizationAccessIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        host = _POSTGRES_HOST
        port = int(os.getenv("TEST_POSTGRES_PORT", "5432"))
        self.authorization_db = AuthorizationDatabase(
            host=host,
            port=port,
            database=os.environ["TEST_AUTHORIZATION_POSTGRES_DB"],
            username=os.environ["TEST_AUTHORIZATION_POSTGRES_USER"],
            password=os.environ["TEST_AUTHORIZATION_POSTGRES_PASSWORD"],
        )
        self.access_db = AccessDatabase(
            host=host,
            port=port,
            database=os.environ["TEST_AUTHORIZATION_POSTGRES_DB"],
            username=os.environ["TEST_AUTHORIZATION_POSTGRES_USER"],
            password=os.environ["TEST_AUTHORIZATION_POSTGRES_PASSWORD"],
        )
        await self.authorization_db.ensure_schema()
        await self.access_db.ensure_schema()

        self.authorization_repository = AuthorizationRepository(self.authorization_db)
        self.access_repository = AccessRepository(self.access_db)
        self.user = await self.authorization_repository.ensure_bootstrap_user(
            "admin",
            "admin",
        )

        namespace = f"mcp-bridge:test:{uuid4().hex}"
        self.cache_settings = ValkeySettings(
            url=os.environ["TEST_VALKEY_URL"],
            namespace=namespace,
        )
        self.cache = SharedCache(self.cache_settings)
        self.authorization_access_settings = AuthorizationServiceSettings.model_construct(
            postgres_host=host,
            postgres_port=port,
            postgres_db=os.environ["TEST_AUTHORIZATION_POSTGRES_DB"],
            postgres_user=os.environ["TEST_AUTHORIZATION_POSTGRES_USER"],
            postgres_password=os.environ["TEST_AUTHORIZATION_POSTGRES_PASSWORD"],
            gateway_service_token="gateway-test",
            admin_service_token="admin-test",
            default_session_ttl_seconds=3600,
            session_cache_ttl_seconds=300,
            invalid_attempt_soft_limit=5,
            invalid_attempt_oauth_revoke_limit=50,
            invalid_attempt_window_seconds=600,
            invalid_attempt_backoff_seconds=30,
        )
        self.access_control = AccessControl(
            settings=self.authorization_access_settings,
            repository=self.access_repository,
            cache=self.cache,
            cache_settings=self.cache_settings,
            revoke_oauth_session=self.authorization_repository.revoke_oauth_session,
        )

    async def asyncTearDown(self) -> None:
        await self.access_control.close()
        await self.access_db.dispose()
        await self.authorization_db.dispose()

    async def test_authorization_database_and_real_oauth_flow(self) -> None:
        authenticated = await self.authorization_repository.authenticate_user("admin", "admin")
        self.assertIsNotNone(authenticated)
        assert authenticated is not None
        self.assertEqual(authenticated.role, "superadmin")
        self.assertIsNone(
            await self.authorization_repository.authenticate_user("admin", "wrong-password")
        )

        settings = AuthorizationServiceSettings.model_construct(
            public_base_url="https://authorization.example.test",
            mcp_public_base_url="https://mcp.example.test",
            postgres_host=_POSTGRES_HOST,
            postgres_port=int(os.getenv("TEST_POSTGRES_PORT", "5432")),
            postgres_db=os.environ["TEST_AUTHORIZATION_POSTGRES_DB"],
            postgres_user=os.environ["TEST_AUTHORIZATION_POSTGRES_USER"],
            postgres_password=os.environ["TEST_AUTHORIZATION_POSTGRES_PASSWORD"],
            bootstrap_username="admin",
            bootstrap_password="admin",
            jwt_signing_key=_signing_key_value(),
            gateway_service_token="gateway-test",
            admin_service_token="admin-test",
            access_token_ttl_seconds=300,
            refresh_token_ttl_seconds=3600,
            allowed_redirect_uris=("https://client.example/callback",),
        )
        provider = LocalOAuthProvider(settings, self.authorization_repository)
        app = build_authorization_app(provider)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://authorization.example.test",
            follow_redirects=False,
        ) as client:
            authenticated_internal = await client.post(
                "/internal/v1/authenticate",
                headers={"Authorization": "Bearer admin-test"},
                json={"username": "admin", "password": "admin"},
            )
            self.assertEqual(
                authenticated_internal.status_code, 200, authenticated_internal.text
            )
            self.assertEqual(authenticated_internal.json()["role"], "superadmin")

            registration = await client.post(
                "/register",
                json={
                    "client_name": "Integration client",
                    "redirect_uris": ["https://client.example/callback"],
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "scope": "read:user",
                },
            )
            self.assertEqual(registration.status_code, 201, registration.text)
            client_id = registration.json()["client_id"]

            verifier = "x" * 64
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .decode()
                .rstrip("=")
            )
            resource = "https://mcp.example.test/terminal/mcp"
            authorize = await client.get(
                "/authorize",
                params={
                    "client_id": client_id,
                    "response_type": "code",
                    "redirect_uri": "https://client.example/callback",
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "scope": "read:user",
                    "state": "integration-state",
                    "resource": resource,
                },
            )
            self.assertEqual(authorize.status_code, 302, authorize.text)
            transaction = parse_qs(
                urlsplit(authorize.headers["location"]).query
            )["transaction"][0]

            login = await client.post(
                "/authorization/login",
                data={
                    "transaction": transaction,
                    "username": "admin",
                    "password": "admin",
                },
            )
            self.assertEqual(login.status_code, 302, login.text)
            code = parse_qs(urlsplit(login.headers["location"]).query)["code"][0]

            token_response = await client.post(
                "/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": "https://client.example/callback",
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "resource": resource,
                },
            )
            self.assertEqual(token_response.status_code, 200, token_response.text)
            tokens = token_response.json()

        access = await provider.load_access_token(tokens["access_token"])
        self.assertIsNotNone(access)
        assert access is not None
        self.assertEqual(access.subject, self.user.id)
        self.assertEqual(access.resource, resource)

    async def test_expired_cached_session_is_persisted_as_expired(self) -> None:
        terminal_surface = int(surface_id("terminal"))
        context = OAuthContext(
            user_id=self.user.id,
            client_id="client-expiry",
            oauth_session_id="oauth-expiry",
        )
        opened = await self.access_control.open_session(
            SessionOpenRequest(
                **context.model_dump(),
                surface_id=terminal_surface,
                label="expiry",
            )
        )
        await self.access_control.admin_update(
            opened.id,
            AdminSessionUpdate(
                admin_user_id=self.user.id,
                expires_at=int(time.time()) - 1,
            ),
        )

        status = await self.access_control.status(
            context=context,
            surface_id=terminal_surface,
            uid=opened.uid,
        )

        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status.status, "expired")

    async def test_selected_scope_requires_account_ids_on_admin_paths(self) -> None:
        github_surface = int(surface_id("github"))
        context = OAuthContext(
            user_id=self.user.id,
            client_id="client-selected",
            oauth_session_id="oauth-selected",
        )
        opened = await self.access_control.open_session(
            SessionOpenRequest(
                **context.model_dump(),
                surface_id=github_surface,
                label="selected",
            )
        )

        with self.assertRaisesRegex(
            ValueError, "selected account scope requires account_ids"
        ):
            await self.access_control.admin_update(
                opened.id,
                AdminSessionUpdate(
                    admin_user_id=self.user.id,
                    access_level="full_access",
                    account_scope="selected",
                    account_ids=[],
                ),
            )

        pending = await self.access_control.request_full_access(
            FullAccessRequest(
                **context.model_dump(),
                surface_id=github_surface,
                session_uid=opened.uid,
                account_scope="selected",
                account_ids=["account-1"],
            )
        )
        with self.assertRaisesRegex(
            ValueError, "selected account scope requires account_ids"
        ):
            await self.access_control.resolve_request(
                pending.id,
                AdminResolveRequest(
                    admin_user_id=self.user.id,
                    approve=True,
                    account_scope="selected",
                    account_ids=[],
                ),
            )

        still_pending = await self.access_repository.list_pending_requests(
            self.user.id
        )
        self.assertTrue(any(item.id == pending.id for item in still_pending))

    async def test_authorization_access_http_contract(self) -> None:
        access_app = build_access_app(self.access_control, self.authorization_access_settings)
        app = Starlette(routes=[Mount("/internal/access", app=access_app)])
        terminal_surface = int(surface_id("terminal"))
        context = {
            "user_id": self.user.id,
            "client_id": "http-client",
            "oauth_session_id": "http-oauth",
        }
        gateway_headers = {"Authorization": "Bearer gateway-test"}
        admin_headers = {"Authorization": "Bearer admin-test"}

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://authorization.test",
        ) as client:
            opened_response = await client.post(
                "/internal/access/v1/session/open",
                headers=gateway_headers,
                json={**context, "surface_id": terminal_surface, "label": "http"},
            )
            self.assertEqual(opened_response.status_code, 200, opened_response.text)
            opened = opened_response.json()
            self.assertEqual(opened["access_level"], "read_only")

            validated = await client.post(
                "/internal/access/v1/session/validate",
                headers=gateway_headers,
                json={
                    **context,
                    "surface_id": terminal_surface,
                    "session_uid": opened["uid"],
                    "tool_name": "terminal_status",
                    "requires_full_access": False,
                    "account_id": "",
                },
            )
            self.assertEqual(validated.status_code, 200, validated.text)
            self.assertTrue(validated.json()["allowed"])

            listed = await client.get(
                f"/internal/access/v1/admin/users/{self.user.id}/sessions",
                headers=admin_headers,
            )
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertTrue(
                any(item["id"] == opened["id"] for item in listed.json()["sessions"])
            )

            elevated = await client.patch(
                f"/internal/access/v1/admin/sessions/{opened['id']}",
                headers=admin_headers,
                json={
                    "admin_user_id": self.user.id,
                    "access_level": "full_access",
                    "account_scope": "none",
                },
            )
            self.assertEqual(elevated.status_code, 200, elevated.text)
            self.assertEqual(elevated.json()["access_level"], "full_access")

            controls = await client.get(
                f"/internal/access/v1/admin/users/{self.user.id}/controls",
                headers=admin_headers,
            )
            self.assertEqual(controls.status_code, 200, controls.text)
            terminal = next(
                item
                for item in controls.json()["controls"]
                if item["surface_id"] == terminal_surface
            )
            self.assertEqual(terminal["mode"], "session_enforced")

    async def test_access_session_persists_and_recovers_after_cache_eviction(self) -> None:
        terminal_surface = int(surface_id("terminal"))
        context = OAuthContext(
            user_id=self.user.id,
            client_id="client-1",
            oauth_session_id="oauth-session-1",
        )
        opened = await self.access_control.open_session(
            SessionOpenRequest(
                **context.model_dump(),
                surface_id=terminal_surface,
                label="integration",
            )
        )

        first = await self.access_control.validate(
            SessionValidateRequest(
                **context.model_dump(),
                surface_id=terminal_surface,
                session_uid=opened.uid,
                tool_name="terminal_status",
                requires_full_access=False,
            )
        )
        self.assertTrue(first.allowed)

        self.assertTrue(
            self.cache.delete(self.access_control._session_key(opened.uid))
        )
        recovered = await self.access_control.validate(
            SessionValidateRequest(
                **context.model_dump(),
                surface_id=terminal_surface,
                session_uid=opened.uid,
                tool_name="terminal_status",
                requires_full_access=False,
            )
        )
        self.assertTrue(recovered.allowed)
        self.assertEqual(recovered.session, opened)

        elevated = await self.access_control.admin_update(
            opened.id,
            AdminSessionUpdate(
                admin_user_id=self.user.id,
                access_level="full_access",
                account_scope="none",
            ),
        )
        self.assertEqual(elevated.access_level, "full_access")

        mutation = await self.access_control.validate(
            SessionValidateRequest(
                **context.model_dump(),
                surface_id=terminal_surface,
                session_uid=opened.uid,
                tool_name="terminal_exec",
                requires_full_access=True,
            )
        )
        self.assertTrue(mutation.allowed)

        await self.access_control.admin_revoke(
            opened.id,
            admin_user_id=self.user.id,
        )
        denied = await self.access_control.validate(
            SessionValidateRequest(
                **context.model_dump(),
                surface_id=terminal_surface,
                session_uid=opened.uid,
                tool_name="terminal_status",
                requires_full_access=False,
            )
        )
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.code, "session_revoked")


if __name__ == "__main__":
    unittest.main()
