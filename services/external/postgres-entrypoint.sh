#!/bin/sh
# Bootstrap four active independent databases in the EXISTING Data PostgreSQL service.
# The upstream entrypoint remains responsible for pg_initdb and normal PGDATA.
set -eu
if [ "${1:-postgres}" != "postgres" ]; then
    exec /usr/local/bin/docker-entrypoint.sh "$@"
fi
: "${POSTGRES_USER:?}"
: "${POSTGRES_PASSWORD:?}"
owner_ready_file=/run/briareus-owner-databases-ready
provider_ready_file=/run/briareus-rauthy-db-ready
rm -f "$owner_ready_file" "$provider_ready_file"
child=
stop_server() {
    if [ -n "$child" ]; then
        kill -TERM "$child" 2>/dev/null || true
        wait "$child" 2>/dev/null || true
    fi
}
trap 'stop_server' INT TERM HUP
/usr/local/bin/docker-entrypoint.sh "$@" &
child=$!
i=0
while [ "$i" -lt 90 ]; do
    if ! kill -0 "$child" 2>/dev/null; then
        wait "$child" || exit $?
        echo 'briareus owner bootstrap: postgres exited before readiness' >&2
        exit 1
    fi
    if pg_isready -h 127.0.0.1 -p 5432 -U "$POSTGRES_USER" -d postgres >/dev/null 2>&1; then
        # This credential stays in process environment; never pass it through
        # argv or echo it. The owner credentials below are consumed exclusively
        # by psql's \getenv and safely quoted with :'variable'.
        export PGPASSWORD="$POSTGRES_PASSWORD"
        # Reconcile the four logical database *names/owners* only. Real
        # service schema migrations belong to their own independent owners.
        if psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 5432 \
            -U "$POSTGRES_USER" -d postgres \
            -f /usr/local/share/briareus/owner-bootstrap.psql >/dev/null; then
            owners_reconciled=true
        else
            owners_reconciled=false
            echo 'briareus domain DB reconciliation failed; PostgreSQL remains running; owner services must fail closed' >&2
        fi
        # Do NOT make the IdP depend on unrelated Platform/Access/Resources
        # database health: a single owner's failure must not block Rauthy.
        # This query proves only the provider DB exists with the scoped owner,
        # not that Rauthy's own startup/schema/users are healthy.
        provider_owned=$(psql -X -qAt -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 5432 \
            -U "$POSTGRES_USER" -d postgres \
            -c "SELECT count(*) = 1 AND bool_and(pg_get_userbyid(datdba) = current_user) FROM pg_database WHERE datname = 'briareus_rauthy'" 2>/dev/null) || provider_owned=f
        if [ "$provider_owned" = t ]; then
            touch "$provider_ready_file"
            if [ "$owners_reconciled" = true ]; then
                touch "$owner_ready_file"
                echo 'briareus owner bootstrap: all four logical databases and existing owner verified'
            else
                echo 'briareus owner bootstrap: provider DB prerequisite ready; unrelated owner DB reconciliation UNVERIFIED' >&2
            fi
        else
            echo 'briareus owner bootstrap: protected provider DB prerequisite UNVERIFIED; Rauthy must not start' >&2
        fi
        unset PGPASSWORD
        wait "$child"
        exit $?
    fi
    i=$((i + 1))
    sleep 1
done
echo 'briareus owner bootstrap: PostgreSQL readiness timeout' >&2
stop_server
exit 1
