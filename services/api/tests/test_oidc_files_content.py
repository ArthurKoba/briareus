"""BFF Files preview DTO: signed-browser-bound selectors, owner fixtures only.

The Files port deliberately has NO production adapter; these tests use a
synthetic owner and Valkey stub. They do not assert real Access/Cedar Permit,
private peer, Files root, disk read or mounted MCP operation.
"""

from __future__ import annotations

import base64
import hashlib
import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from control_panel_api._oidc_browser import _SID_COOKIE, OidcBrowserSessionStore
from control_panel_api._oidc_files_content import (
    FilesContentDenied,
    FilesContentUnavailable,
    PrivateFilesReadCommand,
    VerifiedPrivateFilesRead,
)
from control_panel_api._oidc_id_token import VerifiedOidcIdentity
from control_panel_api._oidc_membership import (
    PlatformMembershipUnavailable,
    PlatformProjectContext,
    ResolvedPlatformUser,
    platform_membership_router,
)
from control_panel_api._oidc_resource import PrivateOidcResourceCredential
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from test_native_pow import AsyncValkeyStub

_ORIGIN = "https://127.0.0.1:18446"
_ISSUER = "https://localhost:18444/auth/v1/"
_CLIENT = "briareus-local-panel"
_RESOURCE = _ORIGIN + "/hands/files/mcp"
_SUBJECT = "F" * 24
_BEARER = "private-signed-fixture-not-real-JWT-" + "Z" * 85
_PAYLOAD = b"owner-approved fixture only\n"


def expiry(seconds: int = 50) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=seconds)


class PlatformFixture:
    def __init__(self, actor: UUID, project: UUID) -> None:
        self.actor, self.project = actor, project
        self.visible = True
        self.current_expires_at = expiry(20)
        self.revision = 1
        self.role = "user"
        self.can_use_resources = True
        self.unavailable = False
        self.calls = 0
        self.revoke_session_after_second_lookup: tuple[OidcBrowserSessionStore, str] | None = None

    async def resolve_project(
        self, *, issuer: str, subject: str, project_uuid: UUID
    ) -> ResolvedPlatformUser | None:
        assert issuer == _ISSUER and subject == _SUBJECT
        self.calls += 1
        if self.unavailable:
            raise PlatformMembershipUnavailable
        if not self.visible or project_uuid != self.project:
            return None
        if self.calls >= 2 and self.revoke_session_after_second_lookup is not None:
            store, ticket = self.revoke_session_after_second_lookup
            await store.delete_session(ticket)
        permissions = ("use_resources",) if self.can_use_resources else ()
        return ResolvedPlatformUser(
            issuer,
            subject,
            self.actor,
            True,
            self.role,
            self.current_expires_at,
            (),
            (PlatformProjectContext(self.project, self.revision, "user", self.actor, permissions),),
        )


class FilesFixture:
    def __init__(self, actor: UUID, project: UUID, store: OidcBrowserSessionStore) -> None:
        self.actor, self.project, self.store = actor, project, store
        self.called = 0
        self.mode = "success"
        self.session_ticket: str | None = None
        self.last_command: PrivateFilesReadCommand | None = None
        self.platform: PlatformFixture | None = None

    async def read(self, command: PrivateFilesReadCommand) -> VerifiedPrivateFilesRead:
        self.called += 1
        self.last_command = command
        assert command.operation_uuid.version == 4
        assert command.issuer == _ISSUER and command.subject == _SUBJECT
        assert command.actor_uuid == self.actor and command.project_uuid == self.project
        assert command.bearer.get_secret_value() == _BEARER
        assert command.proof_expires_at > datetime.now(UTC)
        assert command.selector_id.startswith(f"project-path-v1:{self.project}:")
        assert (
            command.selector_id
            == f"project-path-v1:{self.project}:"
            + hashlib.sha256(
                b"files-project-relative-v1\0" + command.path.encode("utf-8")
            ).hexdigest()
        )
        if self.mode == "denied":
            raise FilesContentDenied
        if self.mode == "unavailable":
            raise FilesContentUnavailable
        if self.mode in {
            "project_revoked_during_read",
            "project_revised_during_read",
            "actor_rebound_during_read",
            "role_changed_during_read",
            "project_permission_removed_during_read",
            "platform_unavailable_during_read",
        }:
            assert self.platform is not None
            if self.mode == "project_revoked_during_read":
                self.platform.visible = False
            elif self.mode == "project_revised_during_read":
                self.platform.revision += 1
            elif self.mode == "actor_rebound_during_read":
                self.platform.actor = uuid4()
            elif self.mode == "role_changed_during_read":
                self.platform.role = "operator"
            elif self.mode == "project_permission_removed_during_read":
                self.platform.can_use_resources = False
            else:
                self.platform.unavailable = True
        if self.mode == "logout_during_read":
            assert self.session_ticket is not None
            await self.store.delete_session(self.session_ticket)
        if self.mode == "platform_proof_expires_during_read":
            assert self.platform is not None
            self.platform.current_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        checked = datetime.now(UTC)
        result = VerifiedPrivateFilesRead(
            operation_uuid=command.operation_uuid,
            actor_uuid=self.actor,
            project_uuid=self.project,
            agent_session_uuid=command.agent_session_uuid,
            grant_revision=command.expected_grant_revision,
            selector_id=command.selector_id,
            path=command.path,
            payload=_PAYLOAD,
            checked_at=checked,
            expires_at=checked + timedelta(seconds=3),
        )
        if self.mode == "cross_project":
            return replace(result, project_uuid=uuid4())
        if self.mode == "wrong_actor":
            return replace(result, actor_uuid=uuid4())
        if self.mode == "wrong_operation":
            return replace(result, operation_uuid=uuid4())
        if self.mode == "wrong_revision":
            return replace(result, grant_revision=command.expected_grant_revision + 1)
        if self.mode == "wrong_selector":
            return replace(result, selector_id=command.selector_id + "x")
        if self.mode == "oversized":
            return replace(result, payload=b"X" * (command.max_bytes + 1))
        if self.mode == "wrong_lifetime":
            return replace(result, expires_at=checked + timedelta(seconds=10))
        return result


class FilesContentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.actor = uuid4()
        self.project = uuid4()
        self.agent_session = uuid4()
        self.memory = AsyncValkeyStub()
        self.sessions = OidcBrowserSessionStore(password=SecretStr("f" * 64), client=self.memory)
        self.platform = PlatformFixture(self.actor, self.project)
        self.owner = FilesFixture(self.actor, self.project, self.sessions)
        self.owner.platform = self.platform
        deadline = expiry()
        identity = VerifiedOidcIdentity(_ISSUER, _SUBJECT, _CLIENT, deadline)
        resource = PrivateOidcResourceCredential(
            _ISSUER,
            _SUBJECT,
            _CLIENT,
            _RESOURCE,
            deadline,
            SecretStr(_BEARER),
        )
        self.ticket, _ = await self.sessions.create_session(identity, resource=resource)
        self.owner.session_ticket = self.ticket
        self.body = {
            "project_uuid": str(self.project),
            "agent_session_uuid": str(self.agent_session),
            "expected_grant_revision": 3,
            "path": "data/проба.txt",
            "max_bytes": 4096,
        }
        self.clients: list[AsyncClient] = []

    async def asyncTearDown(self) -> None:
        for client in reversed(self.clients):
            await client.aclose()

    def client(
        self,
        *,
        owner: FilesFixture | None = None,
        resource: str | None = _RESOURCE,
        cookies: bool = True,
    ) -> AsyncClient:
        app = FastAPI()
        app.include_router(
            platform_membership_router(
                self.sessions,
                source=self.platform,
                files_content_source=owner,
                resource_audience=resource,
                test_only_local_origin=_ORIGIN,
                expected_issuer=_ISSUER,
                expected_client_id=_CLIENT,
            )
        )
        client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url=_ORIGIN,
            cookies={_SID_COOKIE: self.ticket} if cookies else {},
        )
        self.clients.append(client)
        return client

    async def submit(self, client: AsyncClient, **extras: object) -> Response:
        return await client.post(
            "/api/v1/files/read",
            json={**self.body, **extras},
            headers={"Origin": _ORIGIN},
        )

    async def test_default_application_factory_remains_unavailable_for_files_content(self) -> None:
        from unittest.mock import patch

        from control_panel_api.main import create_control_panel_api

        with patch.dict("os.environ", {}, clear=True):
            app = create_control_panel_api()
        async with AsyncClient(transport=ASGITransport(app=app), base_url=_ORIGIN) as client:
            response = await client.post(
                "/api/v1/files/read",
                json=self.body,
                headers={"Origin": _ORIGIN},
            )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "FILES_READ_OWNER_UNAVAILABLE")
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertNotIn("content_base64", response.text)

    async def test_private_owner_return_is_bounded_to_exact_four_field_ui_contract(self) -> None:
        client = self.client(owner=self.owner)
        response = await self.submit(client)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(set(response.json()), {"path", "size_bytes", "sha256", "content_base64"})
        self.assertEqual(response.json()["path"], self.body["path"])
        self.assertEqual(response.json()["size_bytes"], len(_PAYLOAD))
        self.assertEqual(response.json()["sha256"], hashlib.sha256(_PAYLOAD).hexdigest())
        self.assertEqual(base64.b64decode(response.json()["content_base64"]), _PAYLOAD)
        self.assertNotIn(_BEARER, response.text)
        self.assertNotIn(str(self.actor), response.text)
        self.assertEqual(self.owner.called, 1)
        self.assertEqual(self.platform.calls, 2)
        self.assertEqual(self.owner.last_command.expected_grant_revision, 3)
        self.assertEqual(self.owner.last_command.max_bytes, 4096)
        self.assertNotIn(_BEARER, repr(self.owner.last_command))

    async def test_default_has_no_owner_and_no_permission_or_data(self) -> None:
        client = self.client()
        response = await self.submit(client)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "FILES_READ_OWNER_UNAVAILABLE")
        client = self.client(owner=self.owner, resource=None)
        self.assertEqual((await self.submit(client)).status_code, 503)
        self.assertEqual(self.owner.called, 0)
        client = self.client(owner=self.owner, cookies=False)
        self.assertEqual((await self.submit(client)).status_code, 401)
        self.assertEqual(self.owner.called, 0)
        self.platform.visible = False
        client = self.client(owner=self.owner)
        self.assertEqual((await self.submit(client)).status_code, 403)
        self.assertEqual(self.owner.called, 0)
        self.platform.visible = True
        self.assertEqual((await self.submit(client, project_uuid=str(uuid4()))).status_code, 403)
        self.assertEqual(self.owner.called, 0)

    async def test_owner_denial_and_invalid_reply_are_not_browser_data(self) -> None:
        client = self.client(owner=self.owner)
        for mode, status in (
            ("denied", 403),
            ("unavailable", 503),
            ("cross_project", 503),
            ("wrong_actor", 503),
            ("wrong_operation", 503),
            ("wrong_revision", 503),
            ("wrong_selector", 503),
            ("oversized", 503),
            ("wrong_lifetime", 503),
        ):
            self.owner.mode = mode
            response = await self.submit(client)
            self.assertEqual(response.status_code, status, mode)
            self.assertNotIn("content_base64", response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_project_revocation_transfer_and_revalidation_failure_deny_bytes(self) -> None:
        for mode, status in (
            ("project_revoked_during_read", 403),
            ("project_revised_during_read", 403),
            ("actor_rebound_during_read", 403),
            ("role_changed_during_read", 403),
            ("project_permission_removed_during_read", 403),
            ("platform_unavailable_during_read", 503),
        ):
            with self.subTest(mode=mode):
                self.platform = PlatformFixture(self.actor, self.project)
                self.owner.platform = self.platform
                self.owner.mode = mode
                client = self.client(owner=self.owner)
                result = await self.submit(client)
                self.assertEqual(result.status_code, status, result.text)
                self.assertNotIn("content_base64", result.text)
                self.assertEqual(result.headers["cache-control"], "no-store")
                self.assertEqual(self.platform.calls, 2)

    async def test_logout_during_second_platform_revalidation_never_releases_bytes(self) -> None:
        client = self.client(owner=self.owner)
        self.platform.revoke_session_after_second_lookup = (self.sessions, self.ticket)
        response = await self.submit(client)
        self.assertEqual(response.status_code, 401, response.text)
        self.assertNotIn("content_base64", response.text)
        self.assertEqual(self.platform.calls, 2)
        self.assertEqual(self.owner.called, 1)

    async def test_cancelling_actual_cookie_during_owner_read_never_returns_bytes(self) -> None:
        client = self.client(owner=self.owner)
        self.owner.mode = "logout_during_read"
        result = await self.submit(client)
        self.assertEqual(result.status_code, 401)
        self.assertNotIn("content_base64", result.text)
        self.assertEqual(self.owner.called, 1)

    async def test_platform_proof_expired_during_owner_read_blocks_data_release(self) -> None:
        # Clock-dependent 45-ms source leases could expire even BEFORE the
        # owner was called on loaded CI, producing legitimate 403 rather than
        # the formerly asserted 503. Change the signed proof deterministically
        # DURING the fake owner IO, then require a second current-proof read.
        self.owner.mode = "platform_proof_expires_during_read"
        client = self.client(owner=self.owner)
        response = await self.submit(client)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.platform.calls, 2)
        self.assertNotIn("content_base64", response.text)
        self.assertEqual(self.owner.called, 1)

    async def test_invalid_browser_parameters_do_not_contact_private_owner(self) -> None:
        client = self.client(owner=self.owner)
        for changed in (
            {"project_uuid": str(self.project).upper()},
            {"agent_session_uuid": "00000000-0000-0000-0000-000000000000"},
            {"expected_grant_revision": True},
            {"expected_grant_revision": "3"},
            {"max_bytes": 262145},
            {"max_bytes": False},
            {"path": "/etc/passwd"},
            {"path": "../bad"},
            {"path": "normal/../escape"},
            {"path": "C:\\Users\\file"},
            {"path": "illegal//segment"},
            {"path": "a\u0308.txt"},
            {"path": ".upload-" + "a" * 32 + ".tmp"},
            {"path": "X" * 4097},
            {"operation_uuid": str(uuid4())},
        ):
            result = await self.submit(client, **changed)
            self.assertEqual(result.status_code, 422, changed)
            self.assertNotIn("content_base64", result.text)
        self.assertEqual(self.owner.called, 0)

    async def test_duplicate_fields_bad_origin_and_header_credentials_fail_closed(self) -> None:
        client = self.client(owner=self.owner)
        body = json.dumps(self.body)[:-1] + ',"path":"changed.txt"}'
        duplicate = await client.post(
            "/api/v1/files/read",
            content=body,
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
        )
        self.assertEqual(duplicate.status_code, 422)
        wrong = await client.post(
            "/api/v1/files/read",
            json=self.body,
            headers={"Origin": "https://hostile.invalid"},
        )
        self.assertEqual(wrong.status_code, 403)
        auth = await client.post(
            "/api/v1/files/read",
            json=self.body,
            headers={"Origin": _ORIGIN, "Authorization": "Bearer forged"},
        )
        self.assertEqual(auth.status_code, 403)
        with_extra = await client.post(
            "/api/v1/files/read?actor_uuid=" + str(self.actor),
            json=self.body,
            headers={"Origin": _ORIGIN},
        )
        self.assertEqual(with_extra.status_code, 403)
        repeated = await client.post(
            "/api/v1/files/read",
            json=self.body,
            headers={
                "Origin": _ORIGIN,
                "Cookie": f"{_SID_COOKIE}={self.ticket}; {_SID_COOKIE}={self.ticket}",
            },
        )
        self.assertEqual(repeated.status_code, 401)
        self.assertEqual(self.owner.called, 0)
