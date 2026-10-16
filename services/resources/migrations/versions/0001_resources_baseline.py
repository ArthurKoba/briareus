"""Briareus Resources current-schema greenfield baseline (2026-10-15).

This single reviewed revision is for a genuinely EMPTY, correctly scoped
Briareus-owned logical database only. Old Alembic IDs must fail closed.
No migration data adoption, reset, Provider/Rauthy mutation or inferred role.
"""

from __future__ import annotations

from alembic import op

revision = "resources_20261015_0001"
down_revision = None
branch_labels = None
depends_on = None
source_signature = "640be5cf251efb8947d2495520d410cbdc8f78adc4ab8052356d0dfbd1456aea"

_DDL: tuple[str, ...] = (
    ('CREATE SCHEMA "resources"'),
    (
        "CREATE TABLE resources.audit (\n\tid UUID NOT NULL, \n\tope"
        "ration_uuid UUID NOT NULL, \n\tactor_user_id UUID, \n\tproj"
        "ect_id UUID, \n\taction VARCHAR(128) NOT NULL, \n\tobject_i"
        "d VARCHAR(128) NOT NULL, \n\towner_revision VARCHAR(128) "
        "NOT NULL, \n\tdetails JSONB NOT NULL, \n\tcreated_at TIMEST"
        "AMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)"
    ),
    ("CREATE INDEX ix_resources_audit_actor_time ON resources.audit (actor_user_id, created_at)"),
    (
        "CREATE TABLE resources.commands (\n\tid UUID NOT NULL, \n\t"
        "operation_uuid UUID NOT NULL, \n\tactor_scope VARCHAR(64)"
        " NOT NULL, \n\tproject_scope VARCHAR(64) NOT NULL, \n\toper"
        "ation VARCHAR(128) NOT NULL, \n\tkey VARCHAR(128) NOT NUL"
        "L, \n\tfingerprint VARCHAR(64) NOT NULL, \n\texpected_owner"
        "_revision VARCHAR(128) NOT NULL, \n\tstate VARCHAR(16) NO"
        "T NULL, \n\tencrypted_outcome TEXT, \n\tcreated_at TIMESTAM"
        "P WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH "
        "TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZO"
        "NE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_resour"
        "ces_command_state CHECK (state IN ('pending','completed"
        "','unknown','reconciled','denied')), \n\tCONSTRAINT uq_re"
        "sources_command_key UNIQUE (actor_scope, project_scope,"
        " operation, key), \n\tCONSTRAINT uq_resources_command_uui"
        "d_phase UNIQUE (operation_uuid, operation)\n)"
    ),
    ("CREATE INDEX ix_resources_command_reconcile ON resources.commands (state, updated_at)"),
    (
        "CREATE TABLE resources.credential_leases (\n\tid UUID NOT"
        " NULL, \n\tproject_id UUID NOT NULL, \n\tuser_id UUID NOT N"
        "ULL, \n\tsession_uuid UUID NOT NULL, \n\tresource_id UUID N"
        "OT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\towner_scope VAR"
        "CHAR(16) NOT NULL, \n\towner_id UUID NOT NULL, \n\tresource"
        "_version INTEGER NOT NULL, \n\tservice_id UUID, \n\tservice"
        "_instance_uuid UUID, \n\toperation_uuid UUID, \n\tservice_a"
        "udience VARCHAR(64), \n\tcorrelation_id UUID, \n\tproject_v"
        "ersion INTEGER NOT NULL, \n\tproject_resource_revision IN"
        "TEGER NOT NULL, \n\tteam_version INTEGER, \n\tteam_resource"
        "_revision INTEGER, \n\tsession_version INTEGER NOT NULL, "
        "\n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tredee"
        "med_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\t"
        "CONSTRAINT ck_lease_resource_kind CHECK (kind IN ('inte"
        "gration','variable')), \n\tCONSTRAINT ck_lease_service_op"
        "eration_owner CHECK ((service_id IS NULL AND service_in"
        "stance_uuid IS NULL AND operation_uuid IS NULL) OR (ser"
        "vice_id IS NOT NULL AND service_instance_uuid IS NOT NU"
        "LL AND operation_uuid IS NOT NULL)), \n\tCONSTRAINT uq_cr"
        "edential_service_operation UNIQUE (project_id, service_"
        "id, service_instance_uuid, operation_uuid)\n)"
    ),
    ("CREATE INDEX ix_credential_lease_expiry ON resources.credential_leases (expires_at)"),
    (
        "CREATE TABLE resources.integrations (\n\tid UUID NOT NULL"
        ", \n\talias VARCHAR(128) NOT NULL, \n\talias_key VARCHAR(12"
        "8) NOT NULL, \n\tprovider VARCHAR(32) NOT NULL, \n\tauth_ty"
        "pe VARCHAR(32) NOT NULL, \n\tprovider_settings JSONB NOT "
        "NULL, \n\tencrypted_credential TEXT NOT NULL, \n\tversion I"
        "NTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE "
        "NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NUL"
        "L, \n\tdeleted_at TIMESTAMP WITH TIME ZONE, \n\towner_team_"
        "id UUID, \n\towner_project_id UUID, \n\tPRIMARY KEY (id), \n"
        "\tCONSTRAINT ck_integration_owner_xor CHECK ((owner_team"
        "_id IS NOT NULL) <> (owner_project_id IS NOT NULL))\n)"
    ),
    ("CREATE INDEX ix_integration_provider ON resources.integrations (provider, auth_type)"),
    (
        "CREATE UNIQUE INDEX uq_integration_project_alias ON res"
        "ources.integrations (owner_project_id, alias_key) WHERE"
        " owner_project_id IS NOT NULL AND deleted_at IS NULL"
    ),
    (
        "CREATE UNIQUE INDEX uq_integration_team_alias ON resour"
        "ces.integrations (owner_team_id, alias_key) WHERE owner"
        "_team_id IS NOT NULL AND deleted_at IS NULL"
    ),
    (
        "CREATE TABLE resources.outbox (\n\tid UUID NOT NULL, \n\top"
        "eration_uuid UUID NOT NULL, \n\tevent_name VARCHAR(128) N"
        "OT NULL, \n\towner_revision VARCHAR(128) NOT NULL, \n\teven"
        "t_payload JSONB NOT NULL, \n\tattempts INTEGER NOT NULL, "
        "\n\tdelivery_claim_uuid UUID, \n\tavailable_at TIMESTAMP WI"
        "TH TIME ZONE NOT NULL, \n\tclaimed_until TIMESTAMP WITH T"
        "IME ZONE, \n\tdelivered_at TIMESTAMP WITH TIME ZONE, \n\tcr"
        "eated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY K"
        "EY (id), \n\tCONSTRAINT uq_resources_outbox_effect UNIQUE"
        " (operation_uuid, event_name)\n)"
    ),
    ("CREATE INDEX ix_resources_outbox_pending ON resources.outbox (delivered_at, available_at)"),
    (
        "CREATE TABLE resources.variables (\n\tid UUID NOT NULL, \n"
        "\tname_key VARCHAR(128) NOT NULL, \n\tplain_value TEXT, \n\t"
        "encrypted_value TEXT, \n\tis_secret BOOLEAN NOT NULL, \n\tv"
        "ersion INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TI"
        "ME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE"
        " NOT NULL, \n\tdeleted_at TIMESTAMP WITH TIME ZONE, \n\town"
        "er_team_id UUID, \n\towner_project_id UUID, \n\tPRIMARY KEY"
        " (id), \n\tCONSTRAINT ck_variable_owner_xor CHECK ((owner"
        "_team_id IS NOT NULL) <> (owner_project_id IS NOT NULL)"
        "), \n\tCONSTRAINT ck_variable_secret_storage CHECK ((is_s"
        "ecret AND encrypted_value IS NOT NULL AND plain_value I"
        "S NULL) OR (NOT is_secret AND encrypted_value IS NULL A"
        "ND plain_value IS NOT NULL))\n)"
    ),
    (
        "CREATE UNIQUE INDEX uq_variable_project_key ON resource"
        "s.variables (owner_project_id, name_key) WHERE owner_pr"
        "oject_id IS NOT NULL AND deleted_at IS NULL"
    ),
    (
        "CREATE UNIQUE INDEX uq_variable_team_key ON resources.v"
        "ariables (owner_team_id, name_key) WHERE owner_team_id "
        "IS NOT NULL AND deleted_at IS NULL"
    ),
    (
        "CREATE TABLE resources.external_operations (\n\tid UUID N"
        "OT NULL, \n\tactor_id UUID NOT NULL, \n\tproject_id UUID NO"
        "T NULL, \n\tsession_uuid UUID NOT NULL, \n\tresource_id UUI"
        "D NOT NULL, \n\tresource_version INTEGER NOT NULL, \n\tserv"
        "ice_id UUID NOT NULL, \n\tinstance_uuid UUID NOT NULL, \n\t"
        "operation_uuid UUID NOT NULL, \n\toperation VARCHAR(128) "
        "NOT NULL, \n\tidempotency_digest VARCHAR(64) NOT NULL, \n\t"
        "request_fingerprint VARCHAR(64) NOT NULL, \n\tresult_sha2"
        "56 VARCHAR(64), \n\tstatus VARCHAR(16) NOT NULL, \n\tcreate"
        "d_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tdispatched_at"
        " TIMESTAMP WITH TIME ZONE, \n\tresolved_at TIMESTAMP WITH"
        " TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_externa"
        "l_operation_status CHECK (status IN ('reserved', 'dispa"
        "tched', 'succeeded', 'unknown')), \n\tCONSTRAINT uq_exter"
        "nal_operation_identity UNIQUE (actor_id, project_id, op"
        "eration, idempotency_digest), \n\tCONSTRAINT uq_external_"
        "service_operation UNIQUE (project_id, service_id, insta"
        "nce_uuid, operation_uuid), \n\tFOREIGN KEY(resource_id) R"
        "EFERENCES resources.integrations (id) ON DELETE RESTRIC"
        "T\n)"
    ),
    ("CREATE INDEX ix_external_unknown ON resources.external_operations (status, created_at)"),
    (
        "CREATE UNIQUE INDEX uq_external_uncertain_effect ON res"
        "ources.external_operations (project_id, resource_id, op"
        "eration, request_fingerprint) WHERE status IN ('dispatc"
        "hed','unknown')"
    ),
)


def upgrade() -> None:
    # Only ever reached after DB identity/empty-schema owner preflight.
    for statement in _DDL:
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("No destructive fresh owner-schema downgrade")
