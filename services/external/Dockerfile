FROM postgres:18.6-alpine
# Keep the upstream entrypoint and physical volume layout; add only a bounded
# owner-store reconciler before reporting this existing container healthy.
COPY services/external/owner-bootstrap.psql /usr/local/share/briareus/owner-bootstrap.psql
COPY services/external/owner-readiness.psql /usr/local/share/briareus/owner-readiness.psql
COPY services/external/postgres-entrypoint.sh /usr/local/bin/briareus-postgres-entrypoint
COPY services/external/provider-db-health.sh /usr/local/bin/briareus-provider-db-health
RUN chmod 0555 /usr/local/bin/briareus-postgres-entrypoint /usr/local/bin/briareus-provider-db-health
ENTRYPOINT ["/usr/local/bin/briareus-postgres-entrypoint"]
CMD ["postgres"]
