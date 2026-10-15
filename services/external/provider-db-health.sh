#!/bin/sh
# Live read-only PostgreSQL prerequisite for the EXISTING Rauthy service.
# A startup marker alone becomes stale if the provider database is removed or
# ownership changes before a later Rauthy restart. This checks catalog state
# without running owner Alembic, touching users, or emitting secret material.
set -eu
: "${POSTGRES_USER:?}"
: "${POSTGRES_PASSWORD:?}"
test -f /run/briareus-rauthy-db-ready || exit 1
pg_isready -h 127.0.0.1 -p 5432 -U "$POSTGRES_USER" -d postgres >/dev/null 2>&1 || exit 1
export PGPASSWORD="$POSTGRES_PASSWORD"
provider_owned=$(psql -X -qAt -w -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 5432 \
    -U "$POSTGRES_USER" -d postgres \
    -c "SELECT count(*) = 1 AND bool_and(pg_get_userbyid(datdba) = current_user) FROM pg_database WHERE datname = 'briareus_rauthy'" 2>/dev/null) || exit 1
[ "$provider_owned" = t ]
