"""Add private opt-in and bounded browser telemetry counters, no user data.

Revision ID: 0002_browser_telemetry
Revises: 0001_briareus_baseline
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import Boolean, Column, text

revision: str = "0002_browser_telemetry"
down_revision: str | None = "0001_briareus_baseline"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add only an explicit default-denied consent and ephemeral budget table."""
    op.add_column(
        "users",
        Column(
            "browser_telemetry_opt_in", Boolean(),
            nullable=False, server_default=text("false"),
        ),
        schema="identity",
    )
    op.execute(
        '\nCREATE TABLE "authorization".browser_telemetry_budgets (\n\tuser_id UUID NO'
        'T NULL, \n\tscope_kind VARCHAR(16) NOT NULL, \n\tscope_id UUID NOT NULL, \n\tmin'
        'ute_start TIMESTAMP WITH TIME ZONE NOT NULL, \n\tevent_count INTEGER NOT NUL'
        'L, \n\tbyte_count INTEGER NOT NULL, \n\tPRIMARY KEY (user_id, scope_kind, scop'
        'e_id, minute_start), \n\tCONSTRAINT ck_browser_telemetry_scope CHECK (scope_'
        "kind IN ('user','project')), \n\tCONSTRAINT ck_browser_telemetry_budget CHEC"
        'K (event_count >= 0 AND event_count <= 180 AND byte_count >= 0 AND byte_co'
        'unt <= 262144), \n\tFOREIGN KEY(user_id) REFERENCES identity.users (id) ON D'
        'ELETE CASCADE\n)\n\n'
    )


def downgrade() -> None:
    """Never auto-drop stored consent or request-budget history."""
    raise RuntimeError("telemetry schema downgrade requires independently reviewed recovery")
