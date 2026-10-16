"""Real SQL selectors + two ASGI owners; SQLite and signed-peer fixtures only.

No Rauthy user, network peer or physical PostgreSQL grant is fabricated by
these tests. SQLite exercises the ORM query, not PG concurrency/isolation.
"""

from __future__ import annotations

import asyncio
import hashlib
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
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

from common.owner_migrations import (
    _NEW_EPOCH_SOURCE_HASHES,
    OwnerSchemaRejected,
    _ddl_source,
    _require_owner_revision_epoch,
    _upgrade_owner,
    owner_config,
)
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


class GreenfieldOwnerBaselineTests(unittest.TestCase):
    """Existing Platform test module checks Backend's fresh epoch contract.

    No real PostgreSQL or provider user records are accessed by these tests.
    """

    root = Path(__file__).resolve().parents[3]

    def test_platform_current_sql_has_exactly_one_new_epoch_revision(self) -> None:
        config = owner_config("platform")
        history = list(ScriptDirectory.from_config(config).walk_revisions())
        self.assertEqual(len(history), 1)
        module = history[0].module
        self.assertEqual(module.revision, "platform_20261015_0001")
        self.assertIsNone(module.down_revision)
        current = _ddl_source("platform")
        self.assertEqual(module._DDL, current)
        self.assertEqual(
            module.source_signature,
            hashlib.sha256("\n--DDL--\n".join(current).encode()).hexdigest(),
        )
        self.assertEqual(len(current), 26)
        self.assertEqual(
            len(
                [sql for sql in current if sql.startswith("CREATE TABLE control.rauthy_user_links")]
            ),
            1,
        )
        self.assertFalse(
            any(sql.startswith(("DROP", "DELETE", "TRUNCATE", "ALTER")) for sql in current)
        )

    def test_backend_owner_local_and_packaged_baselines_have_no_old_chain(self) -> None:
        for owner, directory, name, revision in (
            ("access", "authorization", "0001_access_baseline.py", "access_20261015_0001"),
            (
                "platform",
                "platform",
                "0001_platform_baseline.py",
                "platform_20261015_0001",
            ),
            (
                "resources",
                "resources",
                "0001_resources_baseline.py",
                "resources_20261015_0001",
            ),
        ):
            with self.subTest(owner=owner):
                local = self.root / "services" / directory / "migrations"
                packaged = self.root / "scripts/alembic_owners" / owner
                files_local = {p.name: p for p in (local / "versions").glob("*.py")}
                files_packaged = {p.name: p for p in (packaged / "versions").glob("*.py")}
                self.assertEqual(set(files_local), {name})
                self.assertEqual(set(files_packaged), {name})
                self.assertEqual(files_local[name].read_bytes(), files_packaged[name].read_bytes())
                config = Config()
                config.set_main_option("script_location", str(packaged))
                source = list(ScriptDirectory.from_config(config).walk_revisions())
                self.assertEqual([m.revision for m in source], [revision])
                self.assertIsNone(source[0].down_revision)
                self.assertEqual(
                    hashlib.sha256(files_packaged[name].read_bytes()).hexdigest(),
                    _NEW_EPOCH_SOURCE_HASHES[revision],
                )
                # One SQL-only fresh baseline, not an unknown historical ALTER.
                import ast

                syntax = ast.parse(files_local[name].read_text())
                ddl = next(
                    ast.literal_eval(node.value)
                    for node in syntax.body
                    if isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and node.target.id == "_DDL"
                )
                self.assertTrue(ddl)
                self.assertTrue(
                    all(
                        sql.startswith(
                            ("CREATE TABLE", "CREATE INDEX", "CREATE UNIQUE INDEX", "CREATE SCHEMA")
                        )
                        for sql in ddl
                    )
                )

    def test_only_new_epoch_or_completely_empty_owner_database_is_eligible(self) -> None:
        for owner, old_versions, fresh in (
            ("access", ("access_0001",), "access_20261015_0001"),
            (
                "platform",
                ("platform_0001", "platform_0002", "platform_0003", "platform_0004"),
                "platform_20261015_0001",
            ),
            ("resources", ("resources_0001", "resources_0002"), "resources_20261015_0001"),
        ):
            with self.subTest(owner=owner):
                _require_owner_revision_epoch(
                    owner, None, contains_objects=False, present_schemas={"public"}
                )
                _require_owner_revision_epoch(
                    owner, fresh, contains_objects=True, present_schemas={"public"}
                )
                for old in old_versions:
                    with self.subTest(previous=old), self.assertRaises(OwnerSchemaRejected):
                        _require_owner_revision_epoch(
                            owner, old, contains_objects=True, present_schemas={"public"}
                        )
                for version, objects, schemas in (
                    (None, True, {"public"}),
                    (None, False, {"public", "control"}),
                    (None, False, {"public", "resources"}),
                ):
                    with self.assertRaises(OwnerSchemaRejected):
                        _require_owner_revision_epoch(
                            owner, version, contains_objects=objects, present_schemas=schemas
                        )

    def test_greenfield_platform_runs_exact_orm_ddl_in_sequence(self) -> None:
        module = next(ScriptDirectory.from_config(owner_config("platform")).walk_revisions()).module
        executed: list[str] = []

        class RecordingBind:
            def exec_driver_sql(self, statement: str) -> None:
                executed.append(statement)

        with patch.object(module.op, "get_bind", return_value=RecordingBind()):
            module.upgrade()
        self.assertEqual(executed, list(_ddl_source("platform")))
        with self.assertRaisesRegex(RuntimeError, "No destructive"):
            module.downgrade()

    def test_old_epoch_is_rejected_before_alembic_upgrade(self) -> None:
        def deny_old(_conn: object, _settings: object) -> None:
            _require_owner_revision_epoch(
                "platform", "platform_0003", contains_objects=True, present_schemas={"public"}
            )

        with (
            patch("common.owner_migrations._identity", side_effect=deny_old),
            patch("common.owner_migrations.command.upgrade") as actual_upgrade,
            self.assertRaises(OwnerSchemaRejected),
        ):
            _upgrade_owner(object(), object(), SimpleNamespace(owner="platform"))
        actual_upgrade.assert_not_called()

    def test_changed_new_epoch_source_is_rejected(self) -> None:
        with (
            patch.dict(_NEW_EPOCH_SOURCE_HASHES, {"platform_20261015_0001": "0" * 64}),
            self.assertRaisesRegex(OwnerSchemaRejected, "greenfield Alembic source changed"),
        ):
            owner_config("platform")
