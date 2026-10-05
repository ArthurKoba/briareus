from __future__ import annotations

import base64
import hashlib
import json
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from mcp.shared.auth import OAuthClientInformationFull

from auth_service.api import build_auth_app
from auth_service.provider import LocalOAuthProvider
from common.settings import AuthServiceSettings


@dataclass
class Transaction:
    id: str
    client_id: str
    params_json: str
    expires_at: datetime


@dataclass
class AuthCode:
    code: str
    client_id: str
    user_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    scopes_json: str
    resource: str
    code_challenge: str
    expires_at: datetime
    consumed_at: datetime | None = None


@dataclass
class RefreshRecord:
    token: str
    session_id: str
    client_id: str
    user_id: str
    scopes_json: str
    resource: str
    expires_at: datetime | None
    revoked_at: datetime | None = None


class FakeAuthRepository:
    def __init__(self) -> None:
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.transactions: dict[str, Transaction] = {}
        self.codes: dict[str, AuthCode] = {}
        self.refresh: dict[str, RefreshRecord] = {}
        self.sessions: dict[str, dict[str, object]] = {}
        self.user = SimpleNamespace(
            id="user-1",
            username="admin",
            enabled=True,
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client: OAuthClientInformationFull) -> None:
        self.clients[client.client_id] = client

    async def create_transaction(
        self,
        *,
        transaction_id: str,
        client_id: str,
        params: dict[str, object],
        expires_at: datetime,
    ) -> None:
        self.transactions[transaction_id] = Transaction(
            id=transaction_id,
            client_id=client_id,
            params_json=json.dumps(params),
            expires_at=expires_at,
        )

    async def load_transaction(self, transaction_id: str) -> Transaction | None:
        record = self.transactions.get(transaction_id)
        if record is None or record.expires_at <= datetime.now(UTC):
            return None
        return record

    async def consume_transaction(self, transaction_id: str) -> Transaction | None:
        record = await self.load_transaction(transaction_id)
        if record is not None:
            self.transactions.pop(transaction_id, None)
        return record

    async def authenticate_user(self, username: str, password: str) -> object | None:
        if username.casefold() == "admin" and password == "admin":
            return self.user
        return None

    async def get_user(self, user_id: str) -> object | None:
        return self.user if user_id == self.user.id else None

    async def create_authorization_code(
        self,
        *,
        code: str,
        client_id: str,
        user_id: str,
        redirect_uri: str,
        redirect_uri_provided_explicitly: bool,
        scopes: list[str],
        resource: str,
        code_challenge: str,
        expires_at: datetime,
    ) -> None:
        record = AuthCode(
            code=code,
            client_id=client_id,
            user_id=user_id,
            redirect_uri=redirect_uri,
            redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
            scopes_json=json.dumps(scopes),
            resource=resource,
            code_challenge=code_challenge,
            expires_at=expires_at,
        )
        self.codes[record.code] = record

    async def load_authorization_code(
        self, client_id: str, code: str
    ) -> AuthCode | None:
        record = self.codes.get(code)
        if (
            record is None
            or record.client_id != client_id
            or record.consumed_at is not None
            or record.expires_at <= datetime.now(UTC)
        ):
            return None
        return record

    async def consume_authorization_code(self, client_id: str, code: str) -> bool:
        record = await self.load_authorization_code(client_id, code)
        if record is None:
            return False
        record.consumed_at = datetime.now(UTC)
        return True

    async def create_oauth_session(
        self, *, user_id: str, client_id: str, resource: str
    ) -> object:
        session_id = f"oauth-{len(self.sessions) + 1}"
        self.sessions[session_id] = {
            "user_id": user_id,
            "client_id": client_id,
            "resource": resource,
            "active": True,
        }
        return SimpleNamespace(id=session_id)

    async def oauth_session_active(
        self, session_id: str, *, user_id: str | None = None
    ) -> bool:
        record = self.sessions.get(session_id)
        if not record or not record["active"]:
            return False
        return user_id is None or record["user_id"] == user_id

    async def touch_oauth_session(self, session_id: str) -> None:
        if session_id not in self.sessions:
            raise AssertionError("unknown OAuth session")

    async def store_refresh_token(
        self,
        *,
        token: str,
        session_id: str,
        client_id: str,
        user_id: str,
        scopes: list[str],
        resource: str,
        expires_at: datetime | None,
    ) -> None:
        self.refresh[token] = RefreshRecord(
            token=token,
            session_id=session_id,
            client_id=client_id,
            user_id=user_id,
            scopes_json=json.dumps(scopes),
            resource=resource,
            expires_at=expires_at,
        )

    async def load_refresh_token(
        self, client_id: str, token: str
    ) -> RefreshRecord | None:
        record = self.refresh.get(token)
        if record is None or record.client_id != client_id or record.revoked_at is not None:
            return None
        if record.expires_at and record.expires_at <= datetime.now(UTC):
            return None
        if not await self.oauth_session_active(record.session_id, user_id=record.user_id):
            return None
        return record

    async def rotate_refresh_token(
        self, client_id: str, old_token: str
    ) -> RefreshRecord | None:
        record = await self.load_refresh_token(client_id, old_token)
        if record is None:
            return None
        record.revoked_at = datetime.now(UTC)
        return record

    async def revoke_oauth_session(self, session_id: str) -> None:
        if session_id in self.sessions:
            self.sessions[session_id]["active"] = False

    async def revoke_refresh_token(self, token: str) -> None:
        record = self.refresh.get(token)
        if record is not None:
            record.revoked_at = datetime.now(UTC)
            await self.revoke_oauth_session(record.session_id)


def private_key_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


class LocalOAuthFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_authorization_code_pkce_and_refresh_rotation(self) -> None:
        repository = FakeAuthRepository()
        settings = AuthServiceSettings.model_construct(
            public_base_url="https://mcp.example.test",
            postgres_host="postgres",
            postgres_port=5432,
            postgres_db="auth",
            postgres_user="auth",
            postgres_password="secret",
            bootstrap_username="admin",
            bootstrap_password="admin",
            jwt_private_key_pem=private_key_pem(),
            jwt_key_id="test-key",
            access_service_token="access-service",
            admin_service_token="admin-service",
            access_token_ttl_seconds=300,
            refresh_token_ttl_seconds=3600,
            allowed_redirect_uris=("https://client.example/callback",),
        )
        provider = LocalOAuthProvider(
            settings,
            repository,  # type: ignore[arg-type]
        )
        app = build_auth_app(provider)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://mcp.example.test",
            follow_redirects=False,
        ) as client:
            registration = await client.post(
                "/register",
                json={
                    "client_name": "Test client",
                    "redirect_uris": ["https://client.example/callback"],
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "scope": "read:user",
                },
            )
            self.assertEqual(registration.status_code, 201, registration.text)
            client_id = registration.json()["client_id"]

            invalid_registration = await client.post(
                "/register",
                json={
                    "client_name": "Invalid client",
                    "redirect_uris": ["https://evil.example/callback"],
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "scope": "read:user",
                },
            )
            self.assertEqual(invalid_registration.status_code, 400)
            self.assertEqual(
                invalid_registration.json()["error"],
                "invalid_redirect_uri",
            )

            verifier = "v" * 64
            digest = hashlib.sha256(verifier.encode()).digest()
            challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
            resource = "https://mcp.example.test/github/mcp"
            authorize = await client.get(
                "/authorize",
                params={
                    "client_id": client_id,
                    "response_type": "code",
                    "redirect_uri": "https://client.example/callback",
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "state": "state-1",
                    "scope": "read:user",
                    "resource": resource,
                },
            )
            self.assertEqual(authorize.status_code, 302, authorize.text)
            login_url = authorize.headers["location"]
            transaction = parse_qs(urlsplit(login_url).query)["transaction"][0]

            login = await client.post(
                "/auth/login",
                data={
                    "transaction": transaction,
                    "username": "admin",
                    "password": "admin",
                },
            )
            self.assertEqual(login.status_code, 302, login.text)
            callback = urlsplit(login.headers["location"])
            callback_query = parse_qs(callback.query)
            self.assertEqual(callback_query["state"], ["state-1"])
            code = callback_query["code"][0]

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
            self.assertEqual(tokens["token_type"], "Bearer")
            self.assertTrue(tokens["access_token"])
            self.assertTrue(tokens["refresh_token"])

            verified = await provider.load_access_token(tokens["access_token"])
            self.assertIsNotNone(verified)
            assert verified is not None
            self.assertEqual(verified.subject, "user-1")
            self.assertEqual(verified.resource, resource)

            refreshed = await client.post(
                "/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                    "client_id": client_id,
                    "scope": "read:user",
                    "resource": resource,
                },
            )
            self.assertEqual(refreshed.status_code, 200, refreshed.text)
            refreshed_tokens = refreshed.json()
            self.assertNotEqual(
                refreshed_tokens["refresh_token"],
                tokens["refresh_token"],
            )

            replay = await client.post(
                "/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                    "client_id": client_id,
                    "scope": "read:user",
                    "resource": resource,
                },
            )
            self.assertIn(replay.status_code, {400, 401})
            self.assertEqual(replay.json()["error"], "invalid_grant")


if __name__ == "__main__":
    unittest.main()
