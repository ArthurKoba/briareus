FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/resources/uv-project/pyproject.toml /app/pyproject.toml
COPY deploy/resources/uv-project/uv.lock /app/uv.lock
COPY deploy/resources/uv-project/.python-version /app/.python-version
RUN --mount=type=cache,target=/root/.cache/uv,sharing=shared uv sync --frozen --no-dev --no-install-project
RUN useradd -u 1000 -m -d /home/briareus briareus
# Source-only uv image: dependency layer cached above; selected service code
# remains uninstalled and runs directly via uv run --no-sync.
COPY scripts/alembic_owners/resources/env.py /app/src/common/alembic_owners/resources/env.py
COPY scripts/alembic_owners/resources/versions/0001_resources_baseline.py /app/src/common/alembic_owners/resources/versions/0001_resources_baseline.py
COPY scripts/alembic_owners/resources/versions/0002_phase_idempotency.py /app/src/common/alembic_owners/resources/versions/0002_phase_idempotency.py
COPY services/common/__init__.py /app/src/common/__init__.py
COPY services/common/account_contracts.py /app/src/common/account_contracts.py
COPY services/common/admin_api_client.py /app/src/common/admin_api_client.py
COPY services/common/cache.py /app/src/common/cache.py
COPY services/common/http_transport.py /app/src/common/http_transport.py
COPY services/common/models.py /app/src/common/models.py
COPY services/common/oauth_session_contracts.py /app/src/common/oauth_session_contracts.py
COPY services/common/observability.py /app/src/common/observability.py
COPY services/common/owner_contracts.py /app/src/common/owner_contracts.py
COPY services/common/owner_migrations.py /app/src/common/owner_migrations.py
COPY services/common/owner_registry.py /app/src/common/owner_registry.py
COPY services/common/owner_runtime.py /app/src/common/owner_runtime.py
COPY services/common/owner_startup_diagnostics.py /app/src/common/owner_startup_diagnostics.py
COPY services/common/owner_transactions.py /app/src/common/owner_transactions.py
COPY services/common/platform_db.py /app/src/common/platform_db.py
COPY services/common/platform_errors.py /app/src/common/platform_errors.py
COPY services/common/platform_ids.py /app/src/common/platform_ids.py
COPY services/common/platform_telemetry.py /app/src/common/platform_telemetry.py
COPY services/common/runtime_policy_contracts.py /app/src/common/runtime_policy_contracts.py
COPY services/common/settings.py /app/src/common/settings.py
COPY services/projects/__init__.py /app/src/projects/__init__.py
COPY services/projects/_catalog_ledger.py /app/src/projects/_catalog_ledger.py
COPY services/projects/_catalog_lifecycle.py /app/src/projects/_catalog_lifecycle.py
COPY services/projects/_catalog_source.py /app/src/projects/_catalog_source.py
COPY services/projects/_provider_registry.py /app/src/projects/_provider_registry.py
COPY services/projects/_resource_domain.py /app/src/projects/_resource_domain.py
COPY services/projects/_resource_persistence.py /app/src/projects/_resource_persistence.py
COPY services/projects/catalog_runtime.py /app/src/projects/catalog_runtime.py
# No installation of the Briareus project: source-only uv run.
COPY deploy/runtime_write_provenance.py /app/runtime_write_provenance.py
RUN python /app/runtime_write_provenance.py resources
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
# Each service starts its OWN Alembic coordinator. Missing DB/grants fail closed.
CMD ["uv", "run", "--frozen", "--no-sync", "--no-dev", "--project", "/app", "--directory", "/app/src", "python", "-m", "uvicorn", "projects.catalog_runtime:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
