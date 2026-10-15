"""Fresh Briareus Platform owner schema for disposable Development database.

This consolidated greenfield baseline replaces the historical Platform 0001-
0004 upgrade chain ONLY after a target-qualified Development DB reset. It
cannot migrate an existing schema. No Rauthy provider or unrelated database
objects are included; PostgreSQL auth/users are managed separately.
"""

from __future__ import annotations

from alembic import op

revision = "platform_0001"
down_revision = None
branch_labels = None
depends_on = None
source_signature = "9207a0eba1c49298b866120c22396ac8f59a0a1066d347b66c3c9a46ef7c99f9"

_DDL: tuple[str, ...] = (
    'CREATE SCHEMA "agents"',
    'CREATE SCHEMA "control"',
    'CREATE SCHEMA "projects"',
    'CREATE SCHEMA "teams"',
    "CREATE TABLE control.audit (\n"
    "\tid UUID NOT NULL, \n"
    "\toperation_uuid UUID NOT NULL, \n"
    "\tactor_user_id UUID, \n"
    "\tproject_id UUID, \n"
    "\taction VARCHAR(128) NOT NULL, \n"
    "\tobject_id VARCHAR(128) NOT NULL, \n"
    "\towner_revision VARCHAR(128) NOT NULL, \n"
    "\tdetails JSONB NOT NULL, \n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tPRIMARY KEY (id)\n"
    ")",
    "CREATE INDEX ix_platform_audit_actor_time ON control.audit (actor_user_id, created_at)",
    "CREATE TABLE control.commands (\n"
    "\tid UUID NOT NULL, \n"
    "\toperation_uuid UUID NOT NULL, \n"
    "\tactor_scope VARCHAR(64) NOT NULL, \n"
    "\tproject_scope VARCHAR(64) NOT NULL, \n"
    "\toperation VARCHAR(128) NOT NULL, \n"
    "\tkey VARCHAR(128) NOT NULL, \n"
    "\tfingerprint VARCHAR(64) NOT NULL, \n"
    "\texpected_owner_revision VARCHAR(128) NOT NULL, \n"
    "\tstate VARCHAR(16) NOT NULL, \n"
    "\tencrypted_outcome TEXT, \n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tPRIMARY KEY (id), \n"
    "\tCONSTRAINT ck_platform_command_state CHECK (state IN "
    "('pending','completed','unknown','reconciled','denied')), \n"
    "\tCONSTRAINT uq_platform_command_key UNIQUE (actor_scope, project_scope, operation, "
    "key), \n"
    "\tCONSTRAINT uq_platform_command_uuid_phase UNIQUE (operation_uuid, operation)\n"
    ")",
    "CREATE INDEX ix_platform_command_reconcile ON control.commands (state, updated_at)",
    "CREATE TABLE control.outbox (\n"
    "\tid UUID NOT NULL, \n"
    "\toperation_uuid UUID NOT NULL, \n"
    "\tevent_name VARCHAR(128) NOT NULL, \n"
    "\towner_revision VARCHAR(128) NOT NULL, \n"
    "\tevent_payload JSONB NOT NULL, \n"
    "\tattempts INTEGER NOT NULL, \n"
    "\tdelivery_claim_uuid UUID, \n"
    "\tavailable_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tclaimed_until TIMESTAMP WITH TIME ZONE, \n"
    "\tdelivered_at TIMESTAMP WITH TIME ZONE, \n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tPRIMARY KEY (id), \n"
    "\tCONSTRAINT uq_platform_outbox_effect UNIQUE (operation_uuid, event_name)\n"
    ")",
    "CREATE INDEX ix_platform_outbox_pending ON control.outbox (delivered_at, available_at)",
    "CREATE TABLE control.rauthy_user_links (\n"
    "\tuser_id UUID NOT NULL, \n"
    "\tissuer VARCHAR(512) NOT NULL, \n"
    "\tsubject VARCHAR(256) NOT NULL, \n"
    "\tbriareus_role VARCHAR(16) NOT NULL, \n"
    "\tactive BOOLEAN NOT NULL, \n"
    "\tversion INTEGER NOT NULL, \n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tPRIMARY KEY (user_id), \n"
    "\tCONSTRAINT uq_rauthy_user_subject UNIQUE (issuer, subject), \n"
    "\tCONSTRAINT ck_rauthy_user_link_role CHECK (briareus_role IN ('user','operator')), \n"
    "\tCONSTRAINT ck_rauthy_user_link_version CHECK (version >= 1)\n"
    ")",
    "CREATE TABLE control.scope_cursors (\n"
    "\tscope_kind VARCHAR(16) NOT NULL, \n"
    "\tscope_id UUID NOT NULL, \n"
    "\tepoch UUID NOT NULL, \n"
    "\trevision BIGINT NOT NULL, \n"
    "\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tPRIMARY KEY (scope_kind, scope_id), \n"
    "\tCONSTRAINT ck_scope_cursor_kind CHECK (scope_kind IN ('user','team','project')), \n"
    "\tCONSTRAINT ck_scope_cursor_revision CHECK (revision >= 0)\n"
    ")",
    "CREATE TABLE control.scope_delivery_receipts (\n"
    "\tid UUID NOT NULL, \n"
    "\tsubscriber_id UUID NOT NULL, \n"
    "\tscope_kind VARCHAR(16) NOT NULL, \n"
    "\tscope_id UUID NOT NULL, \n"
    "\tepoch UUID NOT NULL, \n"
    "\tack_sequence BIGINT NOT NULL, \n"
    "\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tPRIMARY KEY (id), \n"
    "\tCONSTRAINT uq_scope_subscriber_cursor UNIQUE (subscriber_id, scope_kind, scope_id), \n"
    "\tCONSTRAINT ck_scope_ack_revision CHECK (ack_sequence >= 0)\n"
    ")",
    "CREATE TABLE control.scope_events (\n"
    "\tevent_id UUID NOT NULL, \n"
    "\tscope_kind VARCHAR(16) NOT NULL, \n"
    "\tscope_id UUID NOT NULL, \n"
    "\tsequence BIGINT NOT NULL, \n"
    "\tepoch UUID NOT NULL, \n"
    "\tsource_outbox_id UUID NOT NULL, \n"
    "\tevent_type VARCHAR(128) NOT NULL, \n"
    "\tactor_user_id UUID, \n"
    "\tsafe_payload JSONB NOT NULL, \n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tPRIMARY KEY (event_id), \n"
    "\tCONSTRAINT ck_scope_event_kind CHECK (scope_kind IN ('user','team','project')), \n"
    "\tCONSTRAINT ck_scope_event_sequence CHECK (sequence >= 1), \n"
    "\tCONSTRAINT uq_scope_event_sequence UNIQUE (scope_kind, scope_id, sequence), \n"
    "\tCONSTRAINT uq_scope_outbox_ingest UNIQUE (scope_kind, scope_id, source_outbox_id)\n"
    ")",
    "CREATE INDEX ix_scope_event_delivery ON control.scope_events (scope_kind, scope_id, sequence)",
    "CREATE INDEX ix_scope_event_retention ON control.scope_events (expires_at)",
    "CREATE TABLE teams.teams (\n"
    "\tid UUID NOT NULL, \n"
    "\tname VARCHAR(255) NOT NULL, \n"
    "\towner_user_id UUID NOT NULL, \n"
    "\tversion INTEGER NOT NULL, \n"
    "\tresource_revision INTEGER NOT NULL, \n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tPRIMARY KEY (id)\n"
    ")",
    "CREATE INDEX ix_teams_teams_owner_user_id ON teams.teams (owner_user_id)",
    "CREATE TABLE projects.projects (\n"
    "\tid UUID NOT NULL, \n"
    "\tname VARCHAR(255) NOT NULL, \n"
    "\tlifecycle_status VARCHAR(12) DEFAULT 'active' NOT NULL, \n"
    "\towner_user_id UUID, \n"
    "\towner_team_id UUID, \n"
    "\tversion INTEGER NOT NULL, \n"
    "\tresource_revision INTEGER NOT NULL, \n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tPRIMARY KEY (id), \n"
    "\tCONSTRAINT ck_project_exclusive_owner CHECK ((owner_user_id IS NOT NULL) <> "
    "(owner_team_id IS NOT NULL)), \n"
    "\tCONSTRAINT ck_project_lifecycle_status CHECK (lifecycle_status IN "
    "('active','deleting','deleted')), \n"
    "\tFOREIGN KEY(owner_team_id) REFERENCES teams.teams (id) ON DELETE RESTRICT\n"
    ")",
    "CREATE INDEX ix_project_owner_team ON projects.projects (owner_team_id)",
    "CREATE INDEX ix_project_owner_user ON projects.projects (owner_user_id)",
    "CREATE TABLE teams.memberships (\n"
    "\tid UUID NOT NULL, \n"
    "\tteam_id UUID NOT NULL, \n"
    "\tuser_id UUID NOT NULL, \n"
    "\tactive BOOLEAN NOT NULL, \n"
    "\tversion INTEGER NOT NULL, \n"
    "\tPRIMARY KEY (id), \n"
    "\tCONSTRAINT uq_team_membership_user UNIQUE (team_id, user_id), \n"
    "\tFOREIGN KEY(team_id) REFERENCES teams.teams (id) ON DELETE CASCADE\n"
    ")",
    "CREATE INDEX ix_membership_user_active ON teams.memberships (user_id, active)",
    "CREATE INDEX ix_teams_memberships_team_id ON teams.memberships (team_id)",
    "CREATE TABLE agents.identities (\n"
    "\tid UUID NOT NULL, \n"
    "\tproject_id UUID NOT NULL, \n"
    "\tparent_agent_id UUID, \n"
    "\tname VARCHAR(255) NOT NULL, \n"
    "\tenabled BOOLEAN NOT NULL, \n"
    "\tversion INTEGER NOT NULL, \n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tPRIMARY KEY (id), \n"
    "\tCONSTRAINT uq_agent_project_identity UNIQUE (id, project_id), \n"
    "\tCONSTRAINT fk_agent_parent_same_project FOREIGN KEY(parent_agent_id, project_id) "
    "REFERENCES agents.identities (id, project_id), \n"
    "\tFOREIGN KEY(project_id) REFERENCES projects.projects (id) ON DELETE RESTRICT\n"
    ")",
    "CREATE INDEX ix_agent_project_enabled ON agents.identities (project_id, enabled)",
)


def upgrade() -> None:
    for statement in _DDL:
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("No destructive Platform owner-schema downgrade")
