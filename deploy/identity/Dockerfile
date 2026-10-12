FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/identity/uv-project/pyproject.toml /app/pyproject.toml
COPY deploy/identity/uv-project/uv.lock /app/uv.lock
COPY deploy/identity/uv-project/.python-version /app/.python-version
RUN --mount=type=cache,target=/root/.cache/uv,sharing=shared uv sync --frozen --no-dev --no-install-project
RUN useradd -u 1000 -m -d /home/briareus briareus
# Source-only uv image: dependency layer cached above; selected service code
# remains uninstalled and runs directly via uv run --no-sync.
COPY scripts/alembic_owners/identity/env.py /app/src/common/alembic_owners/identity/env.py
COPY scripts/alembic_owners/identity/versions/0001_identity_baseline.py /app/src/common/alembic_owners/identity/versions/0001_identity_baseline.py
COPY scripts/alembic_owners/identity/versions/0002_phase_idempotency.py /app/src/common/alembic_owners/identity/versions/0002_phase_idempotency.py
COPY services/common/__init__.py /app/src/common/__init__.py
COPY services/common/account_contracts.py /app/src/common/account_contracts.py
COPY services/common/admin_api_client.py /app/src/common/admin_api_client.py
COPY services/common/cache.py /app/src/common/cache.py
COPY services/common/credential_primitives.py /app/src/common/credential_primitives.py
COPY services/common/http_transport.py /app/src/common/http_transport.py
COPY services/common/models.py /app/src/common/models.py
COPY services/common/oauth_session_contracts.py /app/src/common/oauth_session_contracts.py
COPY services/common/observability.py /app/src/common/observability.py
COPY services/common/owner_bff_models.py /app/src/common/owner_bff_models.py
COPY services/common/owner_contracts.py /app/src/common/owner_contracts.py
COPY services/common/owner_effect_authorization.py /app/src/common/owner_effect_authorization.py
COPY services/common/owner_migrations.py /app/src/common/owner_migrations.py
COPY services/common/owner_proof_signing.py /app/src/common/owner_proof_signing.py
COPY services/common/owner_registry.py /app/src/common/owner_registry.py
COPY services/common/owner_runtime.py /app/src/common/owner_runtime.py
COPY services/common/owner_startup_diagnostics.py /app/src/common/owner_startup_diagnostics.py
COPY services/common/owner_team_contracts.py /app/src/common/owner_team_contracts.py
COPY services/common/owner_transactions.py /app/src/common/owner_transactions.py
COPY services/common/platform_db.py /app/src/common/platform_db.py
COPY services/common/platform_errors.py /app/src/common/platform_errors.py
COPY services/common/platform_ids.py /app/src/common/platform_ids.py
COPY services/common/platform_telemetry.py /app/src/common/platform_telemetry.py
COPY services/common/private_user_token.py /app/src/common/private_user_token.py
COPY services/common/runtime_policy_contracts.py /app/src/common/runtime_policy_contracts.py
COPY services/common/settings.py /app/src/common/settings.py
COPY services/identity/__init__.py /app/src/identity/__init__.py
COPY services/identity/_account_source.py /app/src/identity/_account_source.py
COPY services/identity/_domain.py /app/src/identity/_domain.py
COPY services/identity/_effect_issuer.py /app/src/identity/_effect_issuer.py
COPY services/identity/_operator_channel.py /app/src/identity/_operator_channel.py
COPY services/identity/_owner_ledger.py /app/src/identity/_owner_ledger.py
COPY services/identity/_owner_proof_reader.py /app/src/identity/_owner_proof_reader.py
COPY services/identity/_persistence.py /app/src/identity/_persistence.py
COPY services/identity/_private_current_user.py /app/src/identity/_private_current_user.py
COPY services/identity/_private_onboarding.py /app/src/identity/_private_onboarding.py
COPY services/identity/_private_user_session.py /app/src/identity/_private_user_session.py
COPY services/identity/_repository.py /app/src/identity/_repository.py
COPY services/identity/_service.py /app/src/identity/_service.py
COPY services/identity/_settings.py /app/src/identity/_settings.py
COPY services/identity/_user_delete_source.py /app/src/identity/_user_delete_source.py
COPY services/identity/platform_runtime.py /app/src/identity/platform_runtime.py
COPY services/identity/private_login_source.py /app/src/identity/private_login_source.py
# No installation of the Briareus project: source-only uv run.
COPY deploy/runtime_write_provenance.py /app/runtime_write_provenance.py
RUN python /app/runtime_write_provenance.py identity
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
# Each service starts its OWN Alembic coordinator. Missing DB/grants fail closed.
CMD ["uv", "run", "--frozen", "--no-sync", "--no-dev", "--project", "/app", "--directory", "/app/src", "python", "-m", "uvicorn", "identity.platform_runtime:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
