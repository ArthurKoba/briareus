"""Source integration: real BFF/client/owner routes with synthetic trust and SQL.

Run with API source on PYTHONPATH and httpx in the locked Authorization runner.
No service credential, physical PostgreSQL or actual Rauthy login is exercised.
"""

from __future__ import annotations

import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from control_panel_api._access_management_client import (
    VerifiedAccessActorDelegation,
    VerifiedAccessTransport,
)
from control_panel_api._access_management_write import PrivateAccessManagementBundle
from control_panel_api._oidc_browser import PanelOidcSession
from control_panel_api._oidc_membership import (
    PlatformProjectContext,
    PlatformTeamContext,
    ResolvedPlatformUser,
    platform_membership_router,
)
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy.sql import Select

from authorization._approval_read_api import (
    ApprovalListCommand,
    ApprovalListReader,
    VerifiedApprovalActor,
    private_approval_list_router,
)

_ORIGIN = "https://briareus.koba-nexus.ru"
_ISSUER = _ORIGIN + "/auth/v1/"
_COOKIE = "source-fixture-cookie-handle-" + "T" * 32
_BEARER = "source-only-not-a-real-bearer-" + "X" * 32


def future(seconds: float = 120) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=seconds)


def session_row(actor: UUID, project: UUID, revision: int = 7) -> SimpleNamespace:
    return SimpleNamespace(
        session_uuid=uuid4(),
        project_id=project,
        created_by_principal_id=actor,
        version=revision,
        status="active",
        revoked_at=None,
        is_elevated=False,
        elevation_policy="requestable",
        hard_expires_at=future(),
        grants={"operations": ["files.read", "project.metadata.read"], "resources": []},
        created_at=datetime.now(UTC),
    )


class ReadOnlySQLFixture:
    engine = SimpleNamespace(url=SimpleNamespace(database="briareus_access"))

    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows
        self.queries: list[dict[str, object]] = []
        self.ignore_scope = False
        self.expire_during_read = False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[ReadOnlySQLFixture]:
        yield self

    async def scalars(self, query: Select) -> list[SimpleNamespace]:
        sql = str(query)
        assert "sessions.agent_sessions" in sql
        parameters = query.compile().params
        self.queries.append(parameters)
        assert parameters.get("project_id_1") is not None
        if self.expire_during_read:
            for row in self.rows:
                row.hard_expires_at = future(-1)
        if self.ignore_scope:
            return self.rows
        rows = [r for r in self.rows if r.project_id == parameters["project_id_1"]]
        if "created_by_principal_id_1" in parameters:
            rows = [
                r
                for r in rows
                if r.created_by_principal_id == parameters["created_by_principal_id_1"]
            ]
        if "session_uuid_1" in parameters:
            rows = [r for r in rows if r.session_uuid == parameters["session_uuid_1"]]
        return sorted(rows, key=lambda r: (r.created_at, r.session_uuid), reverse=True)[
            : parameters["param_1"]
        ]


class ActorFixture:
    def __init__(self, actor: UUID, approver: bool) -> None:
        self.actor = actor
        self.approver = approver

    async def verify(self, request: Request, command: ApprovalListCommand) -> VerifiedApprovalActor:
        assert request.headers["authorization"] == "Bearer " + _BEARER
        return VerifiedApprovalActor(
            self.actor,
            command.project_uuid,
            self.approver,
            "rauthy",
            "briareus:access",
            future(10),
        )


class PrivatePeerFixture:
    def __init__(self, client: AsyncClient, actor: UUID, approver: bool) -> None:
        self.client = client
        self.actor = actor
        self.approver = approver

    async def current_transport(self) -> VerifiedAccessTransport:
        return VerifiedAccessTransport(self.client, "mtls", "briareus:access", future(20))

    async def signed_actor_delegation(
        self, *, actor_uuid: UUID, project_uuid: UUID
    ) -> VerifiedAccessActorDelegation:
        assert actor_uuid == self.actor
        return VerifiedAccessActorDelegation(
            "rauthy",
            actor_uuid,
            project_uuid,
            self.approver,
            SecretStr(_BEARER),
            "briareus:access",
            future(15),
        )


class BrowserSessionFixture:
    async def get_session(self, ticket: str) -> PanelOidcSession | None:
        if ticket != _COOKIE:
            return None
        return PanelOidcSession(_ISSUER, "source-subject", "briareus-control-panel", future())


class PlatformFixture:
    def __init__(self, actor: UUID, project: UUID, approver: bool) -> None:
        self.actor = actor
        self.project = project
        self.team = uuid4()
        self.approver = approver

    async def resolve(self, *, issuer: str, subject: str) -> ResolvedPlatformUser:
        permissions = ("approve_agent_session",) if self.approver else ("use_resources",)
        return ResolvedPlatformUser(
            issuer,
            subject,
            self.actor,
            True,
            "user",
            future(12),
            (PlatformTeamContext(self.team, 1, self.approver),),
            (PlatformProjectContext(self.project, 1, "team", self.team, permissions),),
        )

    async def resolve_project(
        self, *, issuer: str, subject: str, project_uuid: UUID
    ) -> ResolvedPlatformUser | None:
        if project_uuid != self.project:
            return None
        return await self.resolve(issuer=issuer, subject=subject)


class SessionDetailIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.actor = uuid4()
        self.project = uuid4()
        self.target = session_row(self.actor, self.project)
        self.database = ReadOnlySQLFixture([self.target])
        self.clients: list[AsyncClient] = []

    async def asyncTearDown(self) -> None:
        for client in reversed(self.clients):
            await client.aclose()

    def panel(self, *, approver: bool = False, owner_app: FastAPI | None = None) -> AsyncClient:
        if owner_app is None:
            owner_app = FastAPI()
            reader = ApprovalListReader(
                database=self.database, attestor=ActorFixture(self.actor, approver)
            )
            owner_app.include_router(private_approval_list_router(resolve_reader=lambda: reader))
        private = AsyncClient(
            transport=ASGITransport(app=owner_app), base_url="http://briareus-authorization:8000"
        )
        self.clients.append(private)
        peer = PrivatePeerFixture(private, self.actor, approver)
        app = FastAPI()
        app.include_router(
            platform_membership_router(
                BrowserSessionFixture(),
                source=PlatformFixture(self.actor, self.project, approver),
                approval_source=PrivateAccessManagementBundle(trusted_peer=peer),
            )
        )
        public = AsyncClient(transport=ASGITransport(app=app), base_url=_ORIGIN)
        public.cookies.set(
            "__Host-briareus_oidc_session", _COOKIE, domain="briareus.koba-nexus.ru", path="/"
        )
        self.clients.append(public)
        return public

    async def detail(
        self, client: AsyncClient, session: UUID | None = None, project: UUID | None = None
    ) -> Response:
        return await client.get(
            "/api/v1/agent-sessions/" + str(session or self.target.session_uuid),
            params={"project_uuid": str(project or self.project)},
        )

    async def test_exact_current_session_not_limited_to_first_inventory_page(self) -> None:
        self.target.created_at -= timedelta(days=1)
        self.database.rows.extend(session_row(self.actor, self.project) for _ in range(55))
        client = self.panel()
        page = await client.get(
            "/api/v1/agent-sessions", params={"project_uuid": str(self.project)}
        )
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(page.json()["items"]), 50)
        self.assertNotIn(
            str(self.target.session_uuid), {x["session_uuid"] for x in page.json()["items"]}
        )
        detail = await self.detail(client)
        self.assertEqual(detail.status_code, 200, detail.text)
        item = detail.json()
        self.assertEqual(item["session_uuid"], str(self.target.session_uuid))
        self.assertEqual(item["revision"], 7)
        self.assertEqual(item["allowed_actions"], [])
        self.assertEqual(item["resources"], [])
        self.assertEqual(detail.headers["cache-control"], "no-store")
        params = self.database.queries[-1]
        self.assertEqual(params["session_uuid_1"], self.target.session_uuid)
        self.assertEqual(params["created_by_principal_id_1"], self.actor)
        self.assertEqual(params["param_1"], 1)

    async def test_foreign_member_session_hidden_missing_and_foreign_project_denied(self) -> None:
        self.target.created_by_principal_id = uuid4()
        client = self.panel()
        hidden = await self.detail(client)
        absent = await self.detail(client, session=uuid4())
        self.assertEqual(hidden.status_code, 404, hidden.text)
        self.assertEqual(absent.status_code, 404, absent.text)
        self.assertEqual(hidden.json(), absent.json())
        self.assertEqual(hidden.json()["error"]["code"], "AGENT_SESSION_NOT_FOUND")
        before = len(self.database.queries)
        other = await self.detail(client, project=uuid4())
        self.assertEqual(other.status_code, 403)
        self.assertEqual(len(self.database.queries), before)

    async def test_approver_observes_current_revision_and_revoked_state(self) -> None:
        self.target.created_by_principal_id = uuid4()
        client = self.panel(approver=True)
        first = await self.detail(client)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["allowed_actions"], ["revoke"])
        self.assertNotIn("created_by_principal_id_1", self.database.queries[-1])
        # Simulates an independent committed revoke, NOT a live SQL write.
        self.target.version = 8
        self.target.status = "revoked"
        self.target.revoked_at = datetime.now(UTC)
        after = await self.detail(client)
        self.assertEqual(after.status_code, 200, after.text)
        self.assertEqual(after.json()["revision"], 8)
        self.assertEqual(after.json()["status"], "revoked")
        self.assertEqual(after.json()["allowed_actions"], [])

    async def test_sql_wait_expiration_is_not_reported_as_active(self) -> None:
        self.database.expire_during_read = True
        result = await self.detail(self.panel(approver=True))
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "expired")
        self.assertEqual(result.json()["allowed_actions"], [])

    async def test_unknown_private_route_is_unavailable_not_missing_session(self) -> None:
        result = await self.detail(self.panel(owner_app=FastAPI()))
        self.assertEqual(result.status_code, 503, result.text)
        self.assertEqual(result.json()["error"]["code"], "APPROVAL_OWNER_UNAVAILABLE")

    async def test_faulty_private_query_cannot_return_different_session(self) -> None:
        self.database.ignore_scope = True
        client = self.panel()
        result = await self.detail(client, session=uuid4())
        self.assertEqual(result.status_code, 503)
        self.assertNotIn(str(self.target.session_uuid), result.text)

    async def test_anonymous_cookie_never_queries_owner(self) -> None:
        client = self.panel()
        client.cookies.clear()
        result = await self.detail(client)
        self.assertEqual(result.status_code, 401)
        self.assertFalse(self.database.queries)


if __name__ == "__main__":
    unittest.main()
