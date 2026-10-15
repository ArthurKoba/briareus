"""Real SQL selectors + two ASGI owners; SQLite and signed-peer fixtures only.

No Rauthy user, network peer or physical PostgreSQL grant is fabricated by
these tests. SQLite exercises the ORM query, not PG concurrency/isolation.
"""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from control_panel_api._oidc_browser import PanelOidcSession
from control_panel_api._oidc_membership import platform_membership_router
from control_panel_api._platform_current_client import (
    PrivatePlatformCurrentClient,
    VerifiedPanelDelegation,
    VerifiedPlatformServiceTransport,
)
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from projects._oidc_access_project_api import (
    AccessMembershipQuery,
    VerifiedAccessProjectPeer,
    oidc_access_project_router,
)
from projects._oidc_context_api import (
    PlatformContextQuery,
    VerifiedPanelContextPeer,
    current_platform_context_router,
)
from projects._oidc_membership_projection import (
    CurrentRauthyPlatformMembership,
    CurrentRauthyUserLink,
    PlatformOidcMembershipProjection,
    PlatformSubjectLinkUnavailable,
)
from pydantic import SecretStr
from sqlalchemy import create_engine, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Result
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from projects._persistence import ProjectRow
from teams._persistence import TeamMembershipRow, TeamRow

_ISSUER = "https://briareus.koba-nexus.ru/auth/v1/"
_ORIGIN = "https://briareus.koba-nexus.ru"
_COOKIE = "source-only-browser-" + "A" * 40
_SUBJECT = "R" * 24


def deadline() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=20)


class UserLinkFixture:
    def __init__(self, actor: UUID) -> None:
        self.current = CurrentRauthyUserLink(_ISSUER, _SUBJECT, actor, True, "user", 1, deadline())

    async def current_link(self, *, issuer: str, subject: str) -> CurrentRauthyUserLink | None:
        if issuer != self.current.issuer or subject != self.current.subject:
            return None
        return self.current


class QuerySession:
    def __init__(self, session: Session, statements: list[Select]) -> None:
        self.session = session
        self.statements = statements

    async def execute(self, query: Select) -> Result:
        self.statements.append(query)
        return self.session.execute(query)

    async def scalars(self, query: Select) -> object:
        self.statements.append(query)
        return self.session.scalars(query)


class SQLiteOwnerFixture:
    def __init__(self) -> None:
        self.engine = SimpleNamespace(url=SimpleNamespace(database="briareus_platform"))
        self.sql = create_engine(
            "sqlite://",
            execution_options={"schema_translate_map": {"teams": None, "projects": None}},
        )
        for table in (TeamRow.__table__, TeamMembershipRow.__table__, ProjectRow.__table__):
            table.create(self.sql)
        self.statements: list[Select] = []
        self.exit_delay = 0.0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[QuerySession]:
        with Session(self.sql, expire_on_commit=False) as session, session.begin():
            yield QuerySession(session, self.statements)
        if self.exit_delay:
            await asyncio.sleep(self.exit_delay)


class PanelPeerFixture:
    def __init__(self, client: AsyncClient) -> None:
        self.client = client
        self.scope: UUID | None = None
        self.signed: VerifiedPanelDelegation | None = None
        self.bad_scope = False
        self.expires_at = deadline()

    async def current_transport(self) -> VerifiedPlatformServiceTransport:
        self.expires_at = deadline()
        return VerifiedPlatformServiceTransport(
            self.client, "unix-peer", "briareus:platform", self.expires_at
        )

    async def signed_subject_delegation(
        self, *, issuer: str, subject: str
    ) -> VerifiedPanelDelegation:
        return await self._delegate(issuer, subject, None)

    async def signed_project_delegation(
        self, *, issuer: str, subject: str, project_uuid: UUID
    ) -> VerifiedPanelDelegation:
        return await self._delegate(issuer, subject, project_uuid)

    async def _delegate(
        self, issuer: str, subject: str, project: UUID | None
    ) -> VerifiedPanelDelegation:
        self.scope = uuid4() if self.bad_scope else project
        self.signed = VerifiedPanelDelegation(
            SecretStr("fixture-scope-proof-" + "X" * 48),
            subject,
            issuer,
            "briareus:platform",
            self.expires_at,
            self.scope,
        )
        return self.signed

    async def verify(
        self, request: Request, query: PlatformContextQuery
    ) -> VerifiedPanelContextPeer:
        assert request.headers["authorization"].startswith("Bearer fixture-")
        assert query.issuer == _ISSUER and query.subject == _SUBJECT
        assert self.signed is not None
        return VerifiedPanelContextPeer(
            "briareus:platform",
            "control-panel-api",
            _ISSUER,
            _SUBJECT,
            self.expires_at,
            self.scope,
        )


class BrowserFixture:
    async def get_session(self, token: str) -> PanelOidcSession | None:
        if token == _COOKIE:
            return PanelOidcSession(_ISSUER, _SUBJECT, "briareus-control-panel", deadline())
        return None


class ExactProjectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.actor = uuid4()
        self.links = UserLinkFixture(self.actor)
        self.db = SQLiteOwnerFixture()
        self.projection = PlatformOidcMembershipProjection(
            database=self.db, subject_links=self.links
        )
        self.target = uuid4()
        self.team = uuid4()
        with Session(self.db.sql) as session, session.begin():
            # Inventory exceeds both safety caps, but each exact membership
            # still has a bounded and independently checkable owner query.
            for _ in range(105):
                team_id = uuid4()
                session.add(TeamRow(id=team_id, name="fixture", owner_user_id=uuid4()))
                session.add(TeamMembershipRow(team_id=team_id, user_id=self.actor, active=True))
                session.add(ProjectRow(name="fixture", owner_team_id=team_id))
            session.add(TeamRow(id=self.team, name="selected", owner_user_id=self.actor))
            session.add(
                TeamMembershipRow(team_id=self.team, user_id=self.actor, active=True, version=7)
            )
            session.add(
                ProjectRow(id=self.target, name="selected", owner_team_id=self.team, version=4)
            )

    def tearDown(self) -> None:
        self.db.sql.dispose()

    async def exact(self, project: UUID | None = None) -> CurrentRauthyPlatformMembership | None:
        return await self.projection.resolve_project(
            issuer=_ISSUER, subject=_SUBJECT, project_uuid=project or self.target
        )

    async def test_exact_sql_succeeds_beyond_inventory_limit_and_is_scoped(self) -> None:
        with self.assertRaises(PlatformSubjectLinkUnavailable):
            await self.projection.resolve(issuer=_ISSUER, subject=_SUBJECT)
        self.db.statements.clear()
        current = await self.exact()
        self.assertEqual(len(current.projects), 1)
        self.assertEqual(current.projects[0].project_id, self.target)
        self.assertEqual(
            current.projects[0].permissions, ("use_resources", "approve_agent_session")
        )
        self.assertEqual(current.teams[0].version, 7)
        self.assertEqual(len(self.db.statements), 1)
        compiled = self.db.statements[0].compile(dialect=postgresql.dialect())
        self.assertIn(self.target, compiled.params.values())
        self.assertIn("projects.projects.id =", str(compiled))
        self.assertIn("memberships.active IS true", str(compiled))
        self.assertNotIn("LIMIT", str(compiled))

    async def test_current_team_loss_deletion_foreign_and_personal_scope(self) -> None:
        with Session(self.db.sql) as session, session.begin():
            session.execute(
                update(TeamRow).where(TeamRow.id == self.team).values(owner_user_id=uuid4())
            )
        self.assertEqual((await self.exact()).projects[0].permissions, ("use_resources",))
        with Session(self.db.sql) as session, session.begin():
            session.execute(
                update(TeamMembershipRow)
                .where(TeamMembershipRow.team_id == self.team)
                .values(active=False)
            )
        self.assertIsNone(await self.exact())
        self.assertIsNone(await self.exact(uuid4()))
        personal = uuid4()
        with Session(self.db.sql) as session, session.begin():
            session.add(ProjectRow(id=personal, name="personal", owner_user_id=self.actor))
        result = await self.exact(personal)
        self.assertEqual(result.teams, ())
        self.assertEqual(result.projects[0].owner_id, self.actor)
        with Session(self.db.sql) as session, session.begin():
            session.execute(
                update(ProjectRow)
                .where(ProjectRow.id == personal)
                .values(lifecycle_status="deleted")
            )
        self.assertIsNone(await self.exact(personal))

    async def test_disabled_link_and_expiry_at_transaction_exit_deny(self) -> None:
        self.links.current = replace(self.links.current, enabled=False)
        self.assertIsNone(await self.exact())
        self.assertFalse(self.db.statements)
        self.links.current = replace(
            self.links.current,
            enabled=True,
            expires_at=datetime.now(UTC) + timedelta(milliseconds=25),
        )
        self.db.exit_delay = 0.04
        with self.assertRaises(PlatformSubjectLinkUnavailable):
            await self.exact()

    async def test_two_owner_bff_scoped_me_and_sessions_do_not_enumerate(self) -> None:
        app = FastAPI()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://briareus-platform:8000"
        ) as private:
            peer = PanelPeerFixture(private)
            app.include_router(
                current_platform_context_router(projection=self.projection, attestor=peer)
            )
            source = PrivatePlatformCurrentClient(peer=peer)
            public_app = FastAPI()

            class SessionOwner:
                async def list_sessions(
                    owner_self, *, actor: UUID, project: UUID, limit: int
                ) -> tuple:
                    assert actor == self.actor and project == self.target and 1 <= limit <= 50
                    return ()

            public_app.include_router(
                platform_membership_router(
                    BrowserFixture(), source=source, approval_source=SessionOwner()
                )
            )
            async with AsyncClient(
                transport=ASGITransport(app=public_app),
                base_url=_ORIGIN,
                cookies={"__Host-briareus_oidc_session": _COOKIE},
            ) as public:
                ordinary = await public.get("/api/v1/auth/me")
                self.assertEqual(ordinary.status_code, 503)
                scoped = await public.get(
                    "/api/v1/auth/me", params={"project_uuid": str(self.target)}
                )
                self.assertEqual(scoped.status_code, 200, scoped.text)
                self.assertEqual(scoped.json()["projects"][0]["id"], str(self.target))
                self.assertEqual(len(scoped.json()["teams"]), 1)
                sessions = await public.get(
                    "/api/v1/agent-sessions", params={"project_uuid": str(self.target)}
                )
                self.assertEqual(sessions.status_code, 200, sessions.text)
                peer.bad_scope = True
                mismatch = await public.get(
                    "/api/v1/auth/me", params={"project_uuid": str(self.target)}
                )
                self.assertEqual(mismatch.status_code, 503)
                peer.bad_scope = False
                denied = await public.get("/api/v1/auth/me", params={"project_uuid": str(uuid4())})
                self.assertEqual(denied.status_code, 403)
                ambiguous = await public.get(
                    "/api/v1/auth/me",
                    params=[("project_uuid", str(self.target)), ("project_uuid", str(uuid4()))],
                )
                self.assertEqual(ambiguous.status_code, 422)
                self.assertEqual(scoped.headers["cache-control"], "no-store")

    async def test_private_access_route_requires_exact_project_attestation(self) -> None:
        class AccessPeerFixture:
            async def verify(
                peer_self, request: Request, query: AccessMembershipQuery
            ) -> VerifiedAccessProjectPeer:
                assert request.method == "POST" and query.issuer == _ISSUER
                assert query.subject == _SUBJECT
                return VerifiedAccessProjectPeer(
                    "briareus:platform", "authorization", _ISSUER, _SUBJECT, self.target, deadline()
                )

        app = FastAPI()
        app.include_router(
            oidc_access_project_router(projection=self.projection, attestor=AccessPeerFixture())
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://briareus-platform:8000"
        ) as client:
            query = {"issuer": _ISSUER, "subject": _SUBJECT, "project_uuid": str(self.target)}
            response = await client.post(
                "/internal/v1/platform/oidc/project-member",
                json=query,
                headers={"Authorization": "Bearer fixture-peer"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["actor_uuid"], str(self.actor))
            self.assertNotIn("teams", response.json())
            query["project_uuid"] = str(uuid4())
            denied = await client.post(
                "/internal/v1/platform/oidc/project-member",
                json=query,
                headers={"Authorization": "Bearer fixture-peer"},
            )
            self.assertEqual(denied.status_code, 403)
