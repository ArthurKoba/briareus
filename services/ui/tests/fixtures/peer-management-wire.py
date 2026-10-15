"""Actual peer BFF over loopback, with explicit in-memory test authorities.
Not Rauthy, Cedar or SQL acceptance. No production entry imports this fixture.
Run with the peer API Python environment and explicit source / Bun locations.
"""
import argparse
import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import socket
import sys
from uuid import UUID, uuid4
from pydantic import SecretStr

parser = argparse.ArgumentParser()
parser.add_argument('--backend-source', type=Path, required=True)
parser.add_argument('--bun', type=Path, required=True)
args = parser.parse_args()
assert (args.backend_source / 'control_panel_api' / '_oidc_membership.py').is_file()
assert args.bun.is_file()
sys.path.insert(0, str(args.backend_source.resolve()))
import uvicorn
from fastapi import FastAPI
from control_panel_api._oidc_browser import PanelOidcSession
from control_panel_api._oidc_membership import platform_membership_router, ResolvedPlatformUser, PlatformProjectContext, PlatformTeamContext
from control_panel_api._oidc_approvals import (ApprovalSnapshot, CurrentSessionSnapshot, OpenSessionSnapshot, GrantSnapshot,
    OwnerManagementDenied, OwnerManagementNotFound, OwnerManagementConflict, OwnerManagementUnavailable)
from control_panel_api._oidc_catalog import VerifiedCatalogSummary
from control_panel_api._oidc_files_content import (FilesContentDenied,PrivateFilesReadCommand,VerifiedPrivateFilesRead)
from control_panel_api._oidc_resource import PrivateOidcResourceCredential

ISSUER = 'https://identity.example.invalid/auth/v1'
PROJECT = UUID('33333333-3333-4333-8333-333333333333')
USER = UUID('11111111-1111-4111-8111-111111111111')
APPROVER = UUID('22222222-2222-4222-8222-222222222222')
TEAM = UUID('66666666-6666-4666-8666-666666666666')
subjects = {'member': USER, 'approver': APPROVER}
RESOURCE_AUDIENCE = 'https://briareus.koba-nexus.ru/hands/files/mcp'
FILE_PATH = 'wire-fixture.txt'
FILE_SELECTOR = 'project-path-v1:' + str(PROJECT) + ':' + hashlib.sha256(
    b'files-project-relative-v1\0' + FILE_PATH.encode('utf-8')
).hexdigest()
PRIVATE_FIXTURE_BEARER = 'source-only-not-an-oidc-token-' + 'q' * 75
FILE_BYTES = b'only synthetic trusted owner bytes\n'
def expires(seconds): return datetime.now(UTC) + timedelta(seconds=seconds)

class Sessions:
    async def get_session(self, sid):
        subject = {'a' * 48: 'member', 'b' * 48: 'approver'}.get(sid)
        return None if subject is None else PanelOidcSession(ISSUER, subject, 'briareus-control-panel', expires(600))
    async def get_resource_credential(self, sid, *, issuer, client_id, audience):
        subject = {'a' * 48: 'member', 'b' * 48: 'approver'}.get(sid)
        if subject is None or issuer != ISSUER or client_id != 'briareus-control-panel' or audience != RESOURCE_AUDIENCE:
            return None
        return PrivateOidcResourceCredential(
            ISSUER, subject, client_id, RESOURCE_AUDIENCE, expires(600), SecretStr(PRIVATE_FIXTURE_BEARER)
        )

class Membership:
    async def resolve(self, *, issuer, subject): return await self.resolve_project(issuer=issuer, subject=subject, project_uuid=PROJECT)
    async def resolve_project(self, *, issuer, subject, project_uuid):
        if issuer != ISSUER or subject not in subjects or project_uuid != PROJECT: return None
        actor = subjects[subject]
        return ResolvedPlatformUser(ISSUER, subject, actor, True, 'operator' if actor == APPROVER else 'user', expires(25),
            (PlatformTeamContext(TEAM, 1, False),),
            (PlatformProjectContext(PROJECT, 1, 'team', TEAM, ('use_resources', 'approve_agent_session') if actor == APPROVER else ('use_resources',)),))

class Commands:
    def __init__(self):
        self.sessions = {}; self.approvals = {}; self.receipts = {}; self.effects = {'open': 0, 'request': 0, 'resolve': 0, 'revoke': 0}
    def scope(self, actor, project):
        if actor not in subjects.values() or project != PROJECT: raise OwnerManagementDenied()
    async def open_normal(self, *, actor, project, elevation_policy, label, operation):
        self.scope(actor, project)
        key = (actor, operation); intent = ('open', project, elevation_policy, label)
        if key in self.receipts:
            before, result = self.receipts[key]
            if before != intent: raise OwnerManagementConflict()
            return result
        sid = uuid4()
        result = OpenSessionSnapshot(sid, project, 1, 'active', False, elevation_policy, expires(3600), ('files.read', 'project.metadata.read'), ())
        self.sessions[sid] = CurrentSessionSnapshot(sid, project, actor, 1, 'active', False, elevation_policy, result.hard_expires_at, result.operations, (), ())
        self.receipts[key] = (intent, result); self.effects['open'] += 1
        if label == 'lose-once': raise OwnerManagementUnavailable()
        return result
    async def get_session(self, *, actor, project, session):
        self.scope(actor, project); row = self.sessions.get(session)
        if row is None or row.project_uuid != project or (actor != APPROVER and row.created_by_user_uuid != actor): raise OwnerManagementNotFound()
        return replace(row, allowed_actions=('revoke',) if actor == APPROVER and row.status == 'active' else ())
    async def list_sessions(self, *, actor, project, limit):
        self.scope(actor, project)
        return tuple([await self.get_session(actor=actor, project=project, session=sid) for sid, row in self.sessions.items()
            if row.project_uuid == project and (actor == APPROVER or row.created_by_user_uuid == actor)][:limit])
    async def request_elevation(self, *, actor, project, session, operations, resources, seconds, expected_grant_revision, operation):
        row = await self.get_session(actor=actor, project=project, session=session)
        if row.status != 'active' or row.created_by_user_uuid != actor or row.elevation_policy != 'requestable': raise OwnerManagementDenied()
        if row.revision != expected_grant_revision: raise OwnerManagementConflict()
        # Explicit fixture scope, not an attested Files selector or a grant.
        expected = ({'hand': 'files', 'tool': 'read_file', 'action': 'files.read', 'resource': {'kind': 'workspace_path', 'id': FILE_SELECTOR}},)
        if operations != ('files.read',) or resources != expected: raise OwnerManagementDenied()
        result = ApprovalSnapshot(operation, project, session, actor, 'pending', 1, operations, resources, expires(seconds))
        self.approvals[operation] = result; self.effects['request'] += 1
        return result
    async def list_approvals(self, *, actor, project, limit):
        self.scope(actor, project)
        return tuple(row for row in self.approvals.values() if row.project_uuid == project and (actor == APPROVER or row.requested_by_user_uuid == actor))[:limit]
    async def resolve_elevation(self, *, actor, project, approval, expected_version, approve, allowed_operations, operation):
        self.scope(actor, project); row = self.approvals[approval]
        if actor != APPROVER or row.requested_by_user_uuid == actor: raise OwnerManagementDenied()
        if row.status != 'pending' or row.version != expected_version: raise OwnerManagementConflict()
        issued = uuid4() if approve else None
        result = replace(row, status='approved' if approve else 'rejected', version=row.version+1, resolved_by_user_uuid=actor, issued_session_uuid=issued)
        self.approvals[approval] = result; self.effects['resolve'] += 1
        if issued:
            self.sessions[issued] = CurrentSessionSnapshot(issued, project, row.requested_by_user_uuid, 1, 'active', True, 'fixed', row.requested_expires_at, row.requested_operations, row.requested_resources, ())
        return result
    async def revoke_session(self, *, actor, project, session, expected_revision, operation):
        row = await self.get_session(actor=actor, project=project, session=session)
        if actor != APPROVER: raise OwnerManagementDenied()
        if row.revision != expected_revision or row.status != 'active': raise OwnerManagementConflict()
        result = replace(row, status='revoked', revision=row.revision+1, allowed_actions=())
        self.sessions[session] = result; self.effects['revoke'] += 1
        return GrantSnapshot(session, project, 'revoked', result.revision)

class Catalog:
    async def list_metadata(self, *, actor, project, kind, limit):
        if actor not in subjects.values() or project != PROJECT: raise OwnerManagementDenied()
        return (VerifiedCatalogSummary(TEAM, kind, 'project', PROJECT, 'wire.metadata', 1),)

class FilesSourceOnlyFixture:
    """Not a trusted Files Hand: explicit synthetic response for HTTP-shape tests."""
    def __init__(self, commands):
        self.commands=commands
        self.calls=0
    async def read(self, command: PrivateFilesReadCommand) -> VerifiedPrivateFilesRead:
        self.calls+=1
        row=self.commands.sessions.get(command.agent_session_uuid)
        if (command.actor_uuid != USER or command.issuer != ISSUER or command.subject != 'member'
            or command.project_uuid != PROJECT or command.path != FILE_PATH
            or command.selector_id != FILE_SELECTOR or command.max_bytes < len(FILE_BYTES)
            or command.bearer.get_secret_value() != PRIVATE_FIXTURE_BEARER
            or row is None or row.status != 'active'
            or row.created_by_user_uuid != USER or row.project_uuid != PROJECT
            or command.expected_grant_revision != row.revision
            or not any(scope.get('resource', {}).get('id') == FILE_SELECTOR for scope in row.resources)
        ):
            raise FilesContentDenied
        now=datetime.now(UTC)
        return VerifiedPrivateFilesRead(
            command.operation_uuid,command.actor_uuid,command.project_uuid,
            command.agent_session_uuid,command.expected_grant_revision,
            command.selector_id,command.path,FILE_BYTES,now,now+timedelta(seconds=2),
        )

async def main():
    commands = Commands(); files=FilesSourceOnlyFixture(commands); app = FastAPI()
    app.include_router(platform_membership_router(
        Sessions(), source=Membership(), approval_source=commands,
        catalog_source=Catalog(), files_content_source=files,
        resource_audience=RESOURCE_AUDIENCE,
        expected_issuer=ISSUER, expected_client_id='briareus-control-panel',
    ))
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off', access_log=False))
    task = asyncio.create_task(server.serve(sockets=[sock])); process = None
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done(): await task; raise RuntimeError('Wire server did not start')
                await asyncio.sleep(.02)
        process = await asyncio.create_subprocess_exec(str(args.bun), str(Path(__file__).with_suffix('.ts')),
            cwd=Path(__file__).resolve().parents[2], env={**os.environ, 'FRONTEND_WIRE_PORT': str(port)})
        if await asyncio.wait_for(process.wait(), 25): raise RuntimeError('Wire client failed')
        assert commands.effects == {'open': 1, 'request': 2, 'resolve': 2, 'revoke': 1}, commands.effects
        assert files.calls == 2, files.calls
        print('LOCAL_BFF_FILES_OWNER_SYNTHETIC_POST_REVOCATION_DENY_PASS',files.calls,flush=True)
        print('LOCAL_BFF_OWNER_FIXTURE_EFFECTS', commands.effects, flush=True)
    finally:
        if process is not None and process.returncode is None:
            process.terminate(); await asyncio.wait_for(process.wait(), 5)
        server.should_exit = True
        await asyncio.wait_for(task, 5); sock.close()
    print('OWN_BFF_WIRE_SERVER_STOPPED', flush=True)
asyncio.run(main())
