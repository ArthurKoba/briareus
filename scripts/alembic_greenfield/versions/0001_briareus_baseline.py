"""Briareus initial trusted 30-table PostgreSQL schema; frozen source snapshot.

Revision is intentionally independent of current SQLAlchemy ORM metadata.
Never regenerate at runtime or stamp nonempty/foreign databases into it.
Future schema changes become separately reviewed Alembic revisions.

Revision ID: 0001_briareus_baseline
Revises:
"""

from __future__ import annotations

from alembic import op

revision: str = "0001_briareus_baseline"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create ten Briareus schemas with all frozen domain constraints."""
    op.execute(
        'CREATE SCHEMA "agents"'
    )
    op.execute(
        'CREATE SCHEMA "authorization"'
    )
    op.execute(
        'CREATE SCHEMA "files"'
    )
    op.execute(
        'CREATE SCHEMA "identity"'
    )
    op.execute(
        'CREATE SCHEMA "projects"'
    )
    op.execute(
        'CREATE SCHEMA "resources"'
    )
    op.execute(
        'CREATE SCHEMA "reverse"'
    )
    op.execute(
        'CREATE SCHEMA "runtime"'
    )
    op.execute(
        'CREATE SCHEMA "sessions"'
    )
    op.execute(
        'CREATE SCHEMA "teams"'
    )
    op.execute(
        '\nCREATE TABLE "authorization".audit (\n\tid UUID NOT NULL, \n\tactor_id UUID, '
        '\n\tproject_id UUID, \n\taction VARCHAR(128) NOT NULL, \n\tobject_id VARCHAR(128'
        ') NOT NULL, \n\tdetails JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZON'
        'E NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE "authorization".commands (\n\tid UUID NOT NULL, \n\tactor_scope '
        'VARCHAR(64) NOT NULL, \n\tproject_scope VARCHAR(64) NOT NULL, \n\toperation VA'
        'RCHAR(128) NOT NULL, \n\tkey VARCHAR(128) NOT NULL, \n\tfingerprint VARCHAR(64'
        ') NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tresponse_status INTEGER, \n\tre'
        'sponse_ciphertext TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\t'
        'expires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTR'
        "AINT ck_idempotency_status CHECK (status IN ('pending','completed')), \n\tCO"
        'NSTRAINT uq_authorization_command_idempotency UNIQUE (actor_scope, project'
        '_scope, operation, key)\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE "authorization".outbox (\n\tid UUID NOT NULL, \n\tevent_name VAR'
        'CHAR(128) NOT NULL, \n\tevent_payload JSONB NOT NULL, \n\tcreated_at TIMESTAMP'
        ' WITH TIME ZONE NOT NULL, \n\tpublished_at TIMESTAMP WITH TIME ZONE, \n\tclaim'
        '_id UUID, \n\tlocked_until TIMESTAMP WITH TIME ZONE, \n\tattempts INTEGER NOT '
        'NULL, \n\tPRIMARY KEY (id)\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE "authorization".scope_cursors (\n\tscope_kind VARCHAR(16) NOT '
        'NULL, \n\tscope_id UUID NOT NULL, \n\tepoch UUID NOT NULL, \n\trevision BIGINT N'
        'OT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (sc'
        'ope_kind, scope_id), \n\tCONSTRAINT ck_scope_cursor_kind CHECK (scope_kind I'
        "N ('user','team','project')), \n\tCONSTRAINT ck_scope_cursor_revision CHECK "
        '(revision >= 0)\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE "authorization".scope_delivery_receipts (\n\tid UUID NOT NULL,'
        ' \n\tsubscriber_id UUID NOT NULL, \n\tscope_kind VARCHAR(16) NOT NULL, \n\tscope'
        '_id UUID NOT NULL, \n\tepoch UUID NOT NULL, \n\tack_sequence BIGINT NOT NULL, '
        '\n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONS'
        'TRAINT uq_scope_subscriber_cursor UNIQUE (subscriber_id, scope_kind, scope'
        '_id), \n\tCONSTRAINT ck_scope_ack_revision CHECK (ack_sequence >= 0)\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE identity.bootstrap (\n\tid SERIAL NOT NULL, \n\tfirst_superuser_'
        'claimed BOOLEAN NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE identity.login_attempts (\n\tbucket_key VARCHAR(64) NOT NULL, '
        '\n\tfailures INTEGER NOT NULL, \n\tlast_failed_at TIMESTAMP WITH TIME ZONE, \n\t'
        'blocked_until TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (bucket_key)\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE identity.users (\n\tid UUID NOT NULL, \n\tusername VARCHAR(128) '
        'NOT NULL, \n\tpassword_digest TEXT NOT NULL, \n\trole VARCHAR(24) NOT NULL, \n\t'
        'enabled BOOLEAN NOT NULL, \n\tcredential_version INTEGER NOT NULL, \n\tcreated'
        '_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZO'
        'NE NOT NULL, \n\tdeleted_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\t'
        "CONSTRAINT ck_identity_role CHECK (role IN ('user','superuser'))\n)\n\n"
    )
    op.execute(
        '\nCREATE TABLE "authorization".scope_events (\n\tevent_id UUID NOT NULL, \n\tsc'
        'ope_kind VARCHAR(16) NOT NULL, \n\tscope_id UUID NOT NULL, \n\tsequence BIGINT'
        ' NOT NULL, \n\tepoch UUID NOT NULL, \n\tsource_outbox_id UUID NOT NULL, \n\teven'
        't_type VARCHAR(128) NOT NULL, \n\tactor_user_id UUID, \n\tsafe_payload JSONB N'
        'OT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIME'
        'STAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (event_id), \n\tCONSTRAINT ck_s'
        "cope_event_kind CHECK (scope_kind IN ('user','team','project')), \n\tCONSTRA"
        'INT ck_scope_event_sequence CHECK (sequence >= 1), \n\tCONSTRAINT uq_scope_e'
        'vent_sequence UNIQUE (scope_kind, scope_id, sequence), \n\tCONSTRAINT uq_sco'
        'pe_outbox_ingest UNIQUE (scope_kind, scope_id, source_outbox_id), \n\tFOREIG'
        'N KEY(source_outbox_id) REFERENCES "authorization".outbox (id) ON DELETE R'
        'ESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE "authorization".service_keys (\n\tkey_id UUID NOT NULL, \n\tserv'
        'ice_id UUID NOT NULL, \n\tservice_name VARCHAR(80) NOT NULL, \n\taudience VARC'
        'HAR(64) NOT NULL, \n\tkey_version INTEGER NOT NULL, \n\tpublic_key_b64 VARCHAR'
        '(64) NOT NULL, \n\tpublic_key_fingerprint VARCHAR(64) NOT NULL, \n\tenabled BO'
        'OLEAN NOT NULL, \n\tissued_by_user_id UUID NOT NULL, \n\tcreated_at TIMESTAMP '
        'WITH TIME ZONE NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY '
        'KEY (key_id), \n\tCONSTRAINT ck_service_key_version CHECK (key_version >= 1)'
        ', \n\tCONSTRAINT uq_service_identity_audience_revision UNIQUE (service_id, a'
        'udience, key_version), \n\tCONSTRAINT uq_service_public_key UNIQUE (public_k'
        'ey_fingerprint), \n\tFOREIGN KEY(issued_by_user_id) REFERENCES identity.user'
        's (id) ON DELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE identity.admin_token_revocations (\n\tjti_digest VARCHAR(64) N'
        'OT NULL, \n\tuser_id UUID NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NO'
        'T NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (jti'
        '_digest), \n\tFOREIGN KEY(user_id) REFERENCES identity.users (id) ON DELETE '
        'RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE identity.invitations (\n\tid UUID NOT NULL, \n\ttoken_digest VAR'
        'CHAR(64) NOT NULL, \n\tkind VARCHAR(24) NOT NULL, \n\tcreated_by_user_id UUID,'
        ' \n\ttarget_user_id UUID, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\t'
        'expires_at TIMESTAMP WITH TIME ZONE, \n\tused_at TIMESTAMP WITH TIME ZONE, \n'
        '\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tUNIQUE (token_'
        'digest), \n\tFOREIGN KEY(created_by_user_id) REFERENCES identity.users (id) '
        'ON DELETE RESTRICT, \n\tFOREIGN KEY(target_user_id) REFERENCES identity.user'
        's (id) ON DELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE teams.teams (\n\tid UUID NOT NULL, \n\tname VARCHAR(255) NOT NUL'
        'L, \n\towner_user_id UUID NOT NULL, \n\tversion INTEGER NOT NULL, \n\tresource_r'
        'evision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, '
        '\n\tPRIMARY KEY (id), \n\tFOREIGN KEY(owner_user_id) REFERENCES identity.users'
        ' (id) ON DELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE projects.projects (\n\tid UUID NOT NULL, \n\tname VARCHAR(255) N'
        'OT NULL, \n\towner_user_id UUID, \n\towner_team_id UUID, \n\tversion INTEGER NOT'
        ' NULL, \n\tresource_revision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH T'
        'IME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_project_exclusive_o'
        'wner CHECK ((owner_user_id IS NOT NULL) <> (owner_team_id IS NOT NULL)), \n'
        '\tFOREIGN KEY(owner_user_id) REFERENCES identity.users (id) ON DELETE RESTR'
        'ICT, \n\tFOREIGN KEY(owner_team_id) REFERENCES teams.teams (id) ON DELETE RE'
        'STRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE teams.memberships (\n\tid UUID NOT NULL, \n\tteam_id UUID NOT NU'
        'LL, \n\tuser_id UUID NOT NULL, \n\tactive BOOLEAN NOT NULL, \n\tversion INTEGER '
        'NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_team_membership_user UNIQUE '
        '(team_id, user_id), \n\tFOREIGN KEY(team_id) REFERENCES teams.teams (id) ON '
        'DELETE CASCADE, \n\tFOREIGN KEY(user_id) REFERENCES identity.users (id) ON D'
        'ELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE agents.identities (\n\tid UUID NOT NULL, \n\tproject_id UUID NOT'
        ' NULL, \n\tparent_agent_id UUID, \n\tname VARCHAR(255) NOT NULL, \n\tenabled BOO'
        'LEAN NOT NULL, \n\tversion INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIM'
        'E ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_agent_project_identit'
        'y UNIQUE (id, project_id), \n\tCONSTRAINT fk_agent_parent_same_project FOREI'
        'GN KEY(parent_agent_id, project_id) REFERENCES agents.identities (id, proj'
        'ect_id), \n\tFOREIGN KEY(project_id) REFERENCES projects.projects (id) ON DE'
        'LETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE files.file_objects (\n\tid UUID NOT NULL, \n\tproject_id UUID NO'
        'T NULL, \n\tpath_digest VARCHAR(64) NOT NULL, \n\tinode_digest VARCHAR(64), \n\t'
        'content_sha256 VARCHAR(64), \n\tsize_bytes BIGINT NOT NULL, \n\tversion INTEGE'
        'R NOT NULL, \n\tdeleted BOOLEAN NOT NULL, \n\tconfirmed_at TIMESTAMP WITH TIME'
        ' ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_file_object_project_pa'
        'th UNIQUE (project_id, path_digest), \n\tCONSTRAINT uq_file_object_project_i'
        'dentity UNIQUE (id, project_id), \n\tCONSTRAINT ck_file_object_revision CHEC'
        'K (size_bytes >= 0 AND version >= 1), \n\tFOREIGN KEY(project_id) REFERENCES'
        ' projects.projects (id) ON DELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE files.quota_accounts (\n\tproject_id UUID NOT NULL, \n\tbyte_lim'
        'it BIGINT NOT NULL, \n\tused_bytes BIGINT NOT NULL, \n\treserved_bytes BIGINT '
        'NOT NULL, \n\tfrozen BOOLEAN NOT NULL, \n\tversion INTEGER NOT NULL, \n\tupdated'
        '_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (project_id), \n\tCONST'
        'RAINT ck_file_quota_nonnegative CHECK (byte_limit >= 0 AND used_bytes >= 0'
        ' AND reserved_bytes >= 0), \n\tCONSTRAINT ck_file_quota_version CHECK (versi'
        'on >= 1), \n\tFOREIGN KEY(project_id) REFERENCES projects.projects (id) ON D'
        'ELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE resources.integrations (\n\tid UUID NOT NULL, \n\talias VARCHAR('
        '128) NOT NULL, \n\talias_key VARCHAR(128) NOT NULL, \n\tprovider VARCHAR(32) N'
        'OT NULL, \n\tauth_type VARCHAR(32) NOT NULL, \n\tprovider_settings JSONB NOT N'
        'ULL, \n\tencrypted_credential TEXT NOT NULL, \n\tversion INTEGER NOT NULL, \n\tc'
        'reated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH T'
        'IME ZONE NOT NULL, \n\tdeleted_at TIMESTAMP WITH TIME ZONE, \n\towner_team_id '
        'UUID, \n\towner_project_id UUID, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_integra'
        'tion_owner_xor CHECK ((owner_team_id IS NOT NULL) <> (owner_project_id IS '
        'NOT NULL)), \n\tFOREIGN KEY(owner_team_id) REFERENCES teams.teams (id) ON DE'
        'LETE RESTRICT, \n\tFOREIGN KEY(owner_project_id) REFERENCES projects.project'
        's (id) ON DELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE resources.variables (\n\tid UUID NOT NULL, \n\tname_key VARCHAR('
        '128) NOT NULL, \n\tplain_value TEXT, \n\tencrypted_value TEXT, \n\tis_secret BOO'
        'LEAN NOT NULL, \n\tversion INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIM'
        'E ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tdeleted'
        '_at TIMESTAMP WITH TIME ZONE, \n\towner_team_id UUID, \n\towner_project_id UUI'
        'D, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_variable_owner_xor CHECK ((owner_te'
        'am_id IS NOT NULL) <> (owner_project_id IS NOT NULL)), \n\tCONSTRAINT ck_var'
        'iable_secret_storage CHECK ((is_secret AND encrypted_value IS NOT NULL AND'
        ' plain_value IS NULL) OR (NOT is_secret AND encrypted_value IS NULL AND pl'
        'ain_value IS NOT NULL)), \n\tFOREIGN KEY(owner_team_id) REFERENCES teams.tea'
        'ms (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(owner_project_id) REFERENCES pro'
        'jects.projects (id) ON DELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE reverse.native_projects (\n\tid UUID NOT NULL, \n\tproject_id UU'
        'ID NOT NULL, \n\tnative_project_key VARCHAR(256) NOT NULL, \n\towner_service_i'
        'd UUID NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tversion INTEGER NOT NULL, \n'
        '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONST'
        'RAINT uq_reverse_project_native UNIQUE (project_id, native_project_key), \n'
        '\tCONSTRAINT uq_reverse_native_project_scoped UNIQUE (id, project_id), \n\tFO'
        'REIGN KEY(project_id) REFERENCES projects.projects (id) ON DELETE RESTRICT'
        '\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE sessions.agent_sessions (\n\tsession_uuid UUID NOT NULL, \n\tpro'
        'ject_id UUID NOT NULL, \n\tcreated_by_principal_id UUID NOT NULL, \n\tis_eleva'
        'ted BOOLEAN NOT NULL, \n\televation_policy VARCHAR(16) NOT NULL, \n\tlabel VAR'
        'CHAR(128), \n\tgrants JSONB NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tversi'
        'on INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\thar'
        'd_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_at TIMESTAMP WIT'
        'H TIME ZONE, \n\tPRIMARY KEY (session_uuid), \n\tCONSTRAINT ck_agent_session_u'
        "uid_v4 CHECK (substr(cast(session_uuid AS text), 15, 1) = '4'), \n\tCONSTRAI"
        "NT ck_agent_session_elevation_policy CHECK (elevation_policy IN ('fixed','"
        "requestable')), \n\tCONSTRAINT ck_agent_session_status CHECK (status IN ('ac"
        "tive','revoked')), \n\tFOREIGN KEY(project_id) REFERENCES projects.projects "
        '(id) ON DELETE RESTRICT, \n\tFOREIGN KEY(created_by_principal_id) REFERENCES'
        ' identity.users (id) ON DELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE "authorization".consumed_assertions (\n\tid UUID NOT NULL, \n\tk'
        'ind VARCHAR(16) NOT NULL, \n\tissuer_id UUID NOT NULL, \n\tjti_digest VARCHAR('
        '64) NOT NULL, \n\tproject_id UUID NOT NULL, \n\tsession_uuid UUID NOT NULL, \n\t'
        'expires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcreated_at TIMESTAMP WITH '
        'TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_assertion_kind CHE'
        "CK (kind IN ('service','delegation')), \n\tCONSTRAINT uq_assertion_single_us"
        'e UNIQUE (kind, issuer_id, jti_digest), \n\tFOREIGN KEY(project_id) REFERENC'
        'ES projects.projects (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(session_uuid) '
        'REFERENCES sessions.agent_sessions (session_uuid) ON DELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE "authorization".external_operations (\n\tid UUID NOT NULL, \n\ta'
        'ctor_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tsession_uuid UUID NOT'
        ' NULL, \n\tresource_id UUID NOT NULL, \n\tresource_version INTEGER NOT NULL, \n'
        '\tservice_id UUID NOT NULL, \n\tinstance_uuid UUID NOT NULL, \n\toperation_uuid'
        ' UUID NOT NULL, \n\toperation VARCHAR(128) NOT NULL, \n\tidempotency_digest VA'
        'RCHAR(64) NOT NULL, \n\trequest_fingerprint VARCHAR(64) NOT NULL, \n\tresult_s'
        'ha256 VARCHAR(64), \n\tstatus VARCHAR(16) NOT NULL, \n\tcreated_at TIMESTAMP W'
        'ITH TIME ZONE NOT NULL, \n\tdispatched_at TIMESTAMP WITH TIME ZONE, \n\tresolv'
        'ed_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_extern'
        "al_operation_status CHECK (status IN ('reserved', 'dispatched', 'succeeded"
        "', 'unknown')), \n\tCONSTRAINT uq_external_operation_identity UNIQUE (actor_"
        'id, project_id, operation, idempotency_digest), \n\tCONSTRAINT uq_external_s'
        'ervice_operation UNIQUE (project_id, service_id, instance_uuid, operation_'
        'uuid), \n\tFOREIGN KEY(actor_id) REFERENCES identity.users (id) ON DELETE RE'
        'STRICT, \n\tFOREIGN KEY(project_id) REFERENCES projects.projects (id) ON DEL'
        'ETE RESTRICT, \n\tFOREIGN KEY(session_uuid) REFERENCES sessions.agent_sessio'
        'ns (session_uuid) ON DELETE RESTRICT, \n\tFOREIGN KEY(resource_id) REFERENCE'
        'S resources.integrations (id) ON DELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE files.quota_reservations (\n\treservation_id UUID NOT NULL, \n\t'
        'operation_uuid UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tagent_session_'
        'uuid UUID NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\towner_service_id UUID'
        ' NOT NULL, \n\tpath_digest VARCHAR(64) NOT NULL, \n\tidempotency_digest VARCHA'
        'R(64) NOT NULL, \n\trequest_fingerprint VARCHAR(64) NOT NULL, \n\texpected_con'
        'tent_sha256 VARCHAR(64) NOT NULL, \n\tproject_access_revision VARCHAR(64) NO'
        'T NULL, \n\texpected_file_version INTEGER NOT NULL, \n\tprior_bytes BIGINT NOT'
        ' NULL, \n\tplanned_bytes BIGINT NOT NULL, \n\treserved_delta BIGINT NOT NULL, '
        '\n\tversion INTEGER NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tcreated_at TI'
        'MESTAMP WITH TIME ZONE NOT NULL, \n\tdispatched_at TIMESTAMP WITH TIME ZONE,'
        ' \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tresolved_at TIMESTAMP W'
        'ITH TIME ZONE, \n\tobserved_inode_digest VARCHAR(64), \n\tobserved_file_versio'
        'n INTEGER, \n\tobserved_size_bytes BIGINT, \n\tPRIMARY KEY (reservation_id), \n'
        "\tCONSTRAINT ck_file_quota_reservation_state CHECK (status IN ('reserved','"
        "dispatched','committed','released','unknown')), \n\tCONSTRAINT ck_file_reser"
        'vation_size CHECK (prior_bytes >= 0 AND planned_bytes >= 0 AND reserved_de'
        'lta >= 0), \n\tCONSTRAINT ck_file_reservation_version CHECK (version >= 1 AN'
        'D expected_file_version >= 0), \n\tCONSTRAINT uq_file_quota_idempotency UNIQ'
        'UE (project_id, idempotency_digest), \n\tCONSTRAINT uq_file_quota_operation_'
        'uuid UNIQUE (project_id, operation_uuid), \n\tCONSTRAINT ck_file_operation_u'
        "uid_v4 CHECK (substr(cast(operation_uuid AS text), 15, 1) = '4'), \n\tFOREIG"
        'N KEY(project_id) REFERENCES projects.projects (id) ON DELETE RESTRICT, \n\t'
        'FOREIGN KEY(agent_session_uuid) REFERENCES sessions.agent_sessions (sessio'
        'n_uuid) ON DELETE RESTRICT, \n\tFOREIGN KEY(actor_user_id) REFERENCES identi'
        'ty.users (id) ON DELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE resources.credential_leases (\n\tid UUID NOT NULL, \n\tproject_i'
        'd UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\tsession_uuid UUID NOT NULL, \n\t'
        'resource_id UUID NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\towner_scope VARC'
        'HAR(16) NOT NULL, \n\towner_id UUID NOT NULL, \n\tresource_version INTEGER NOT'
        ' NULL, \n\tservice_id UUID, \n\tservice_instance_uuid UUID, \n\toperation_uuid U'
        'UID, \n\tservice_audience VARCHAR(64), \n\tcorrelation_id UUID, \n\tproject_vers'
        'ion INTEGER NOT NULL, \n\tproject_resource_revision INTEGER NOT NULL, \n\tteam'
        '_version INTEGER, \n\tteam_resource_revision INTEGER, \n\tsession_version INTE'
        'GER NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tredeemed_a'
        't TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_lease_reso'
        "urce_kind CHECK (kind IN ('integration','variable')), \n\tCONSTRAINT ck_leas"
        'e_service_operation_owner CHECK ((service_id IS NULL AND service_instance_'
        'uuid IS NULL AND operation_uuid IS NULL) OR (service_id IS NOT NULL AND se'
        'rvice_instance_uuid IS NOT NULL AND operation_uuid IS NOT NULL)), \n\tCONSTR'
        'AINT uq_credential_service_operation UNIQUE (project_id, service_id, servi'
        'ce_instance_uuid, operation_uuid), \n\tFOREIGN KEY(project_id) REFERENCES pr'
        'ojects.projects (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(user_id) REFERENCES'
        ' identity.users (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(session_uuid) REFER'
        'ENCES sessions.agent_sessions (session_uuid) ON DELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE reverse.native_imports (\n\timport_uuid UUID NOT NULL, \n\topera'
        'tion_uuid UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tnative_project_id U'
        'UID NOT NULL, \n\tfile_object_id UUID NOT NULL, \n\tsource_file_version INTEGE'
        'R NOT NULL, \n\tsource_content_sha256 VARCHAR(64) NOT NULL, \n\tsource_size_by'
        'tes INTEGER NOT NULL, \n\tauto_analyze BOOLEAN NOT NULL, \n\tactor_user_id UUI'
        'D NOT NULL, \n\tagent_session_uuid UUID NOT NULL, \n\towner_service_id UUID NO'
        'T NULL, \n\tidempotency_digest VARCHAR(64) NOT NULL, \n\trequest_fingerprint V'
        'ARCHAR(64) NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tversion INTEGER NOT '
        'NULL, \n\tnative_artifact_id VARCHAR(256), \n\tresult_sha256 VARCHAR(64), \n\tcl'
        'eanup_state VARCHAR(20) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NO'
        'T NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tdispatched_at TI'
        'MESTAMP WITH TIME ZONE, \n\tresolved_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY '
        'KEY (import_uuid), \n\tCONSTRAINT fk_native_import_project_owner FOREIGN KEY'
        '(native_project_id, project_id) REFERENCES reverse.native_projects (id, pr'
        'oject_id), \n\tCONSTRAINT fk_native_import_source_project FOREIGN KEY(file_o'
        'bject_id, project_id) REFERENCES files.file_objects (id, project_id), \n\tCO'
        "NSTRAINT ck_native_import_status CHECK (status IN ('reserved','dispatched'"
        ",'succeeded','unknown','confirmed_absent','cancelled')), \n\tCONSTRAINT ck_n"
        "ative_import_cleanup_state CHECK (cleanup_state IN ('not_requested','reque"
        "sted','confirmed')), \n\tCONSTRAINT ck_native_import_version CHECK (version "
        '>= 1 AND source_file_version >= 1 AND source_size_bytes >= 0), \n\tCONSTRAIN'
        "T ck_native_import_success_id CHECK ((status = 'succeeded' AND native_arti"
        "fact_id IS NOT NULL) OR (status <> 'succeeded')), \n\tCONSTRAINT uq_native_i"
        'mport_idempotency UNIQUE (project_id, idempotency_digest), \n\tCONSTRAINT uq'
        '_native_import_operation_uuid UNIQUE (project_id, operation_uuid), \n\tCONST'
        'RAINT ck_native_import_operation_uuid_v4 CHECK (substr(cast(operation_uuid'
        " AS text), 15, 1) = '4'), \n\tFOREIGN KEY(project_id) REFERENCES projects.pr"
        'ojects (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(actor_user_id) REFERENCES id'
        'entity.users (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(agent_session_uuid) RE'
        'FERENCES sessions.agent_sessions (session_uuid) ON DELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE runtime.sessions (\n\truntime_session_uuid UUID NOT NULL, \n\tpr'
        'oject_id UUID NOT NULL, \n\tagent_session_uuid UUID NOT NULL, \n\tactor_user_i'
        'd UUID NOT NULL, \n\tkind VARCHAR(20) NOT NULL, \n\towner_service_id UUID NOT '
        'NULL, \n\towner_instance UUID NOT NULL, \n\topen_idempotency_digest VARCHAR(64'
        ') NOT NULL, \n\topen_request_fingerprint VARCHAR(64) NOT NULL, \n\tlease_nonce'
        ' UUID NOT NULL, \n\tversion INTEGER NOT NULL, \n\tstatus VARCHAR(16) NOT NULL,'
        ' \n\tcleanup_state VARCHAR(16) NOT NULL, \n\tidle_ttl_seconds INTEGER NOT NULL'
        ', \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlast_heartbeat_at TIME'
        'STAMP WITH TIME ZONE NOT NULL, \n\tidle_expires_at TIMESTAMP WITH TIME ZONE '
        'NOT NULL, \n\thard_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlease_exp'
        'ires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tended_at TIMESTAMP WITH TIME '
        'ZONE, \n\tPRIMARY KEY (runtime_session_uuid), \n\tCONSTRAINT ck_runtime_kind C'
        "HECK (kind IN ('files','terminal','web_managed','web_remote','reverse')), "
        "\n\tCONSTRAINT ck_runtime_status CHECK (status IN ('active','lost','expired'"
        ",'revoked','closed')), \n\tCONSTRAINT ck_runtime_cleanup_state CHECK (cleanu"
        "p_state IN ('not_needed','pending','confirmed','unknown')), \n\tCONSTRAINT c"
        'k_runtime_lease_revision CHECK (version >= 1 AND idle_ttl_seconds >= 30 AN'
        'D idle_ttl_seconds <= 86400), \n\tCONSTRAINT ck_runtime_hard_lease CHECK (ha'
        'rd_expires_at > created_at AND lease_expires_at <= hard_expires_at), \n\tCON'
        'STRAINT ck_runtime_session_uuid_v4 CHECK (substr(cast(runtime_session_uuid'
        " AS text), 15, 1) = '4'), \n\tCONSTRAINT uq_runtime_project_session UNIQUE ("
        'runtime_session_uuid, project_id), \n\tCONSTRAINT uq_runtime_session_open_de'
        'dup UNIQUE (project_id, owner_service_id, actor_user_id, agent_session_uui'
        'd, kind, open_idempotency_digest), \n\tFOREIGN KEY(project_id) REFERENCES pr'
        'ojects.projects (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(agent_session_uuid)'
        ' REFERENCES sessions.agent_sessions (session_uuid) ON DELETE RESTRICT, \n\tF'
        'OREIGN KEY(actor_user_id) REFERENCES identity.users (id) ON DELETE RESTRIC'
        'T\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE sessions.approvals (\n\tid UUID NOT NULL, \n\tsession_uuid UUID '
        'NOT NULL, \n\tproject_id UUID NOT NULL, \n\trequested_by_user_id UUID NOT NULL'
        ', \n\trequested_grants JSONB NOT NULL, \n\trequested_expires_at TIMESTAMP WITH'
        ' TIME ZONE NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tversion INTEGER NOT '
        'NULL, \n\tresolved_by_user_id UUID, \n\tissued_session_uuid UUID, \n\tresolved_a'
        't TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL'
        ', \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_session_approval_status CHECK (statu'
        "s IN ('pending','approved','rejected')), \n\tCONSTRAINT ck_session_approval_"
        'version CHECK (version >= 1), \n\tFOREIGN KEY(session_uuid) REFERENCES sessi'
        'ons.agent_sessions (session_uuid) ON DELETE RESTRICT, \n\tFOREIGN KEY(projec'
        't_id) REFERENCES projects.projects (id) ON DELETE RESTRICT, \n\tFOREIGN KEY('
        'requested_by_user_id) REFERENCES identity.users (id) ON DELETE RESTRICT, \n'
        '\tFOREIGN KEY(resolved_by_user_id) REFERENCES identity.users (id) ON DELETE'
        ' RESTRICT, \n\tFOREIGN KEY(issued_session_uuid) REFERENCES sessions.agent_se'
        'ssions (session_uuid) ON DELETE RESTRICT\n)\n\n'
    )
    op.execute(
        '\nCREATE TABLE runtime.jobs (\n\tjob_uuid UUID NOT NULL, \n\truntime_session_uu'
        'id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\towner_service_id UUID NOT '
        'NULL, \n\tactor_user_id UUID NOT NULL, \n\tagent_session_uuid UUID NOT NULL, \n'
        '\tidempotency_digest VARCHAR(64) NOT NULL, \n\trequest_fingerprint VARCHAR(64'
        ') NOT NULL, \n\toperation VARCHAR(128) NOT NULL, \n\tstatus VARCHAR(16) NOT NU'
        'LL, \n\tversion INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT '
        'NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE, \n\tresolved_at TIMESTAMP WITH '
        'TIME ZONE, \n\thard_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tresult_d'
        'igest VARCHAR(64), \n\tPRIMARY KEY (job_uuid), \n\tCONSTRAINT fk_runtime_job_p'
        'roject_session FOREIGN KEY(runtime_session_uuid, project_id) REFERENCES ru'
        'ntime.sessions (runtime_session_uuid, project_id), \n\tCONSTRAINT ck_runtime'
        "_job_status CHECK (status IN ('queued','running','succeeded','failed','unk"
        "nown','cancelled')), \n\tCONSTRAINT ck_runtime_job_version CHECK (version >="
        ' 1), \n\tCONSTRAINT uq_runtime_job_idempotency UNIQUE (project_id, runtime_s'
        'ession_uuid, idempotency_digest), \n\tFOREIGN KEY(project_id) REFERENCES pro'
        'jects.projects (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(actor_user_id) REFER'
        'ENCES identity.users (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(agent_session_'
        'uuid) REFERENCES sessions.agent_sessions (session_uuid) ON DELETE RESTRICT'
        '\n)\n\n'
    )
    op.execute(
        'CREATE INDEX ix_authorization_audit_actor_time ON "authorization".audit (a'
        'ctor_id, created_at)'
    )
    op.execute(
        'CREATE INDEX ix_authorization_command_expiry ON "authorization".commands ('
        'expires_at)'
    )
    op.execute(
        'CREATE INDEX ix_auth_outbox_pending ON "authorization".outbox (published_a'
        't, created_at)'
    )
    op.execute(
        'CREATE INDEX ix_identity_user_active_role ON identity.users (enabled, role'
        ')'
    )
    op.execute(
        'CREATE UNIQUE INDEX ix_identity_users_username ON identity.users (username'
        ')'
    )
    op.execute(
        'CREATE INDEX ix_scope_event_delivery ON "authorization".scope_events (scop'
        'e_kind, scope_id, sequence)'
    )
    op.execute(
        'CREATE INDEX ix_scope_event_retention ON "authorization".scope_events (exp'
        'ires_at)'
    )
    op.execute(
        'CREATE INDEX ix_service_key_audience_enabled ON "authorization".service_ke'
        'ys (audience, enabled)'
    )
    op.execute(
        'CREATE INDEX ix_admin_revocation_expires_at ON identity.admin_token_revoca'
        'tions (expires_at)'
    )
    op.execute(
        'CREATE INDEX ix_identity_invitation_pending ON identity.invitations (kind,'
        ' used_at, revoked_at)'
    )
    op.execute(
        'CREATE INDEX ix_teams_teams_owner_user_id ON teams.teams (owner_user_id)'
    )
    op.execute(
        'CREATE INDEX ix_project_owner_team ON projects.projects (owner_team_id)'
    )
    op.execute(
        'CREATE INDEX ix_project_owner_user ON projects.projects (owner_user_id)'
    )
    op.execute(
        'CREATE INDEX ix_membership_user_active ON teams.memberships (user_id, acti'
        've)'
    )
    op.execute(
        'CREATE INDEX ix_teams_memberships_team_id ON teams.memberships (team_id)'
    )
    op.execute(
        'CREATE INDEX ix_agent_project_enabled ON agents.identities (project_id, en'
        'abled)'
    )
    op.execute(
        'CREATE INDEX ix_file_object_project_deleted ON files.file_objects (project'
        '_id, deleted)'
    )
    op.execute(
        'CREATE INDEX ix_integration_provider ON resources.integrations (provider, '
        'auth_type)'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_integration_project_alias ON resources.integrations'
        ' (owner_project_id, alias_key) WHERE owner_project_id IS NOT NULL AND dele'
        'ted_at IS NULL'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_integration_team_alias ON resources.integrations (o'
        'wner_team_id, alias_key) WHERE owner_team_id IS NOT NULL AND deleted_at IS'
        ' NULL'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_variable_project_key ON resources.variables (owner_'
        'project_id, name_key) WHERE owner_project_id IS NOT NULL AND deleted_at IS'
        ' NULL'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_variable_team_key ON resources.variables (owner_tea'
        'm_id, name_key) WHERE owner_team_id IS NOT NULL AND deleted_at IS NULL'
    )
    op.execute(
        'CREATE INDEX ix_native_project_project ON reverse.native_projects (project'
        '_id, enabled)'
    )
    op.execute(
        'CREATE INDEX ix_agent_session_project_active ON sessions.agent_sessions (p'
        'roject_id, status)'
    )
    op.execute(
        'CREATE INDEX ix_assertion_expiry ON "authorization".consumed_assertions (e'
        'xpires_at)'
    )
    op.execute(
        'CREATE INDEX ix_external_unknown ON "authorization".external_operations (s'
        'tatus, created_at)'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_external_uncertain_effect ON "authorization".extern'
        'al_operations (project_id, resource_id, operation, request_fingerprint) WH'
        "ERE status IN ('dispatched','unknown')"
    )
    op.execute(
        'CREATE INDEX ix_quota_reservation_expiry ON files.quota_reservations (stat'
        'us, expires_at)'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_file_active_path ON files.quota_reservations (proje'
        "ct_id, path_digest) WHERE status IN ('reserved','dispatched','unknown')"
    )
    op.execute(
        'CREATE INDEX ix_credential_lease_expiry ON resources.credential_leases (ex'
        'pires_at)'
    )
    op.execute(
        'CREATE INDEX ix_native_import_uncertain ON reverse.native_imports (status,'
        ' created_at)'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_native_artifact_in_project ON reverse.native_import'
        's (native_project_id, native_artifact_id) WHERE native_artifact_id IS NOT '
        'NULL'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_native_uncertain_effect ON reverse.native_imports ('
        'project_id, native_project_id, file_object_id, source_file_version, reques'
        "t_fingerprint) WHERE status IN ('dispatched','unknown')"
    )
    op.execute(
        'CREATE INDEX ix_runtime_expiry ON runtime.sessions (status, idle_expires_a'
        't, hard_expires_at)'
    )
    op.execute(
        'CREATE INDEX ix_runtime_owner ON runtime.sessions (project_id, owner_servi'
        'ce_id, status)'
    )
    op.execute(
        'CREATE INDEX ix_session_approval_status ON sessions.approvals (project_id,'
        ' status)'
    )
    op.execute(
        'CREATE INDEX ix_runtime_job_pending ON runtime.jobs (status, hard_expires_'
        'at)'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_runtime_uncertain_effect ON runtime.jobs (runtime_s'
        "ession_uuid, request_fingerprint) WHERE status IN ('queued','running','unk"
        "nown')"
    )


def downgrade() -> None:
    """Never destroy first-production schema with automatic downgrade."""
    raise RuntimeError(
        "initial Briareus schema cannot be downgraded without an independently"
        " reviewed data-preserving recovery plan"
    )
