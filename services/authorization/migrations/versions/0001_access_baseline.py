"""Briareus Access current-schema greenfield baseline (2026-10-15).

This single reviewed revision is for a genuinely EMPTY, correctly scoped
Briareus-owned logical database only. Old Alembic IDs must fail closed.
No migration data adoption, reset, Provider/Rauthy mutation or inferred role.
"""

from __future__ import annotations

from alembic import op

revision = "access_20261015_0001"
down_revision = None
branch_labels = None
depends_on = None
source_signature = "b9db1f587cb5412d7d08616acac58468d910c9a535bc9b7de77a5570a1652b2c"

_DDL: tuple[str, ...] = (
    ('CREATE SCHEMA "access"'),
    ('CREATE SCHEMA "authorization"'),
    ('CREATE SCHEMA "sessions"'),
    (
        "CREATE TABLE access.audit (\n\tid UUID NOT NULL, \n\tactor_"
        "id UUID, \n\tproject_id UUID, \n\taction VARCHAR(128) NOT N"
        "ULL, \n\tobject_id VARCHAR(128) NOT NULL, \n\tdetails JSONB"
        " NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NU"
        "LL, \n\tPRIMARY KEY (id)\n)"
    ),
    ("CREATE INDEX ix_authorization_audit_actor_time ON access.audit (actor_id, created_at)"),
    (
        "CREATE TABLE access.commands (\n\tid UUID NOT NULL, \n\tact"
        "or_scope VARCHAR(64) NOT NULL, \n\tproject_scope VARCHAR("
        "64) NOT NULL, \n\toperation VARCHAR(128) NOT NULL, \n\tkey "
        "VARCHAR(128) NOT NULL, \n\tfingerprint VARCHAR(64) NOT NU"
        "LL, \n\tstatus VARCHAR(24) NOT NULL, \n\tresponse_status IN"
        "TEGER, \n\tresponse_ciphertext TEXT, \n\tcreated_at TIMESTA"
        "MP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH"
        " TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT c"
        "k_idempotency_status CHECK (status IN ('pending','compl"
        "eted')), \n\tCONSTRAINT uq_authorization_command_idempote"
        "ncy UNIQUE (actor_scope, project_scope, operation, key)"
        "\n)"
    ),
    ("CREATE INDEX ix_authorization_command_expiry ON access.commands (expires_at)"),
    (
        "CREATE TABLE access.outbox (\n\tid UUID NOT NULL, \n\tevent"
        "_name VARCHAR(128) NOT NULL, \n\tevent_payload JSONB NOT "
        "NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
        "\tpublished_at TIMESTAMP WITH TIME ZONE, \n\tclaim_id UUID"
        ", \n\tlocked_until TIMESTAMP WITH TIME ZONE, \n\tattempts I"
        "NTEGER NOT NULL, \n\tPRIMARY KEY (id)\n)"
    ),
    ("CREATE INDEX ix_auth_outbox_pending ON access.outbox (published_at, created_at)"),
    (
        'CREATE TABLE "authorization".service_keys (\n\tkey_id UUI'
        "D NOT NULL, \n\tservice_id UUID NOT NULL, \n\tservice_name "
        "VARCHAR(80) NOT NULL, \n\taudience VARCHAR(64) NOT NULL, "
        "\n\tkey_version INTEGER NOT NULL, \n\tpublic_key_b64 VARCHA"
        "R(64) NOT NULL, \n\tpublic_key_fingerprint VARCHAR(64) NO"
        "T NULL, \n\tenabled BOOLEAN NOT NULL, \n\tissued_by_user_id"
        " UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE N"
        "OT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tPRIMA"
        "RY KEY (key_id), \n\tCONSTRAINT ck_service_key_version CH"
        "ECK (key_version >= 1), \n\tCONSTRAINT uq_service_identit"
        "y_audience_revision UNIQUE (service_id, audience, key_v"
        "ersion), \n\tCONSTRAINT uq_service_public_key UNIQUE (pub"
        "lic_key_fingerprint)\n)"
    ),
    (
        'CREATE INDEX ix_service_key_audience_enabled ON "author'
        'ization".service_keys (audience, enabled)'
    ),
    (
        "CREATE TABLE sessions.agent_sessions (\n\tsession_uuid UU"
        "ID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tcreated_by_p"
        "rincipal_id UUID NOT NULL, \n\tis_elevated BOOLEAN NOT NU"
        "LL, \n\televation_policy VARCHAR(16) NOT NULL, \n\tlabel VA"
        "RCHAR(128), \n\tgrants JSONB NOT NULL, \n\tstatus VARCHAR(1"
        "6) NOT NULL, \n\tversion INTEGER NOT NULL, \n\tcreated_at T"
        "IMESTAMP WITH TIME ZONE NOT NULL, \n\thard_expires_at TIM"
        "ESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_at TIMESTAMP "
        "WITH TIME ZONE, \n\tPRIMARY KEY (session_uuid), \n\tCONSTRA"
        "INT ck_agent_session_uuid_v4 CHECK (substr(cast(session"
        "_uuid AS text), 15, 1) = '4'), \n\tCONSTRAINT ck_agent_se"
        "ssion_elevation_policy CHECK (elevation_policy IN ('fix"
        "ed','requestable')), \n\tCONSTRAINT ck_agent_session_stat"
        "us CHECK (status IN ('active','revoked'))\n)"
    ),
    (
        "CREATE INDEX ix_agent_session_project_active ON session"
        "s.agent_sessions (project_id, status)"
    ),
    (
        'CREATE TABLE "authorization".consumed_assertions (\n\tid '
        "UUID NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\tissuer_id"
        " UUID NOT NULL, \n\tjti_digest VARCHAR(64) NOT NULL, \n\tpr"
        "oject_id UUID NOT NULL, \n\tsession_uuid UUID NOT NULL, \n"
        "\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcreate"
        "d_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY ("
        "id), \n\tCONSTRAINT ck_assertion_kind CHECK (kind IN ('se"
        "rvice','delegation')), \n\tCONSTRAINT uq_assertion_single"
        "_use UNIQUE (kind, issuer_id, jti_digest), \n\tFOREIGN KE"
        "Y(session_uuid) REFERENCES sessions.agent_sessions (ses"
        "sion_uuid) ON DELETE RESTRICT\n)"
    ),
    ('CREATE INDEX ix_assertion_expiry ON "authorization".consumed_assertions (expires_at)'),
    (
        "CREATE TABLE sessions.approvals (\n\tid UUID NOT NULL, \n\t"
        "session_uuid UUID NOT NULL, \n\tproject_id UUID NOT NULL,"
        " \n\trequested_by_user_id UUID NOT NULL, \n\trequested_gran"
        "ts JSONB NOT NULL, \n\trequested_expires_at TIMESTAMP WIT"
        "H TIME ZONE NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\t"
        "version INTEGER NOT NULL, \n\tresolved_by_user_id UUID, \n"
        "\tissued_session_uuid UUID, \n\tresolved_at TIMESTAMP WITH"
        " TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT N"
        "ULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_session_approv"
        "al_status CHECK (status IN ('pending','approved','rejec"
        "ted')), \n\tCONSTRAINT ck_session_approval_version CHECK "
        "(version >= 1), \n\tFOREIGN KEY(session_uuid) REFERENCES "
        "sessions.agent_sessions (session_uuid) ON DELETE RESTRI"
        "CT, \n\tFOREIGN KEY(issued_session_uuid) REFERENCES sessi"
        "ons.agent_sessions (session_uuid) ON DELETE RESTRICT\n)"
    ),
    ("CREATE INDEX ix_session_approval_status ON sessions.approvals (project_id, status)"),
)


def upgrade() -> None:
    # Only ever reached after DB identity/empty-schema owner preflight.
    for statement in _DDL:
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("No destructive fresh owner-schema downgrade")
