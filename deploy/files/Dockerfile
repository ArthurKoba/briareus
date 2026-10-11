FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/files/uv-project/pyproject.toml /app/pyproject.toml
COPY deploy/files/uv-project/uv.lock /app/uv.lock
COPY deploy/files/uv-project/.python-version /app/.python-version
RUN --mount=type=cache,target=/root/.cache/uv,sharing=shared uv sync --frozen --no-dev --no-install-project
ENV ASGI_APP=modules.files.runtime:app
RUN useradd -u 1000 -m -d /home/bridge bridge \
    && mkdir -p /workspace \
    && chown -R 1000:1000 /workspace /home/bridge
# Source-only uv image: dependency layer cached above; selected service code
# remains uninstalled and runs directly via uv run --no-sync.
COPY services/common/__init__.py /app/src/common/__init__.py
COPY services/common/account_contracts.py /app/src/common/account_contracts.py
COPY services/common/admin_api_client.py /app/src/common/admin_api_client.py
COPY services/common/asgi.py /app/src/common/asgi.py
COPY services/common/audit_payloads.py /app/src/common/audit_payloads.py
COPY services/common/cache.py /app/src/common/cache.py
COPY services/common/http_transport.py /app/src/common/http_transport.py
COPY services/common/models.py /app/src/common/models.py
COPY services/common/oauth_session_contracts.py /app/src/common/oauth_session_contracts.py
COPY services/common/observability.py /app/src/common/observability.py
COPY services/common/owner_contracts.py /app/src/common/owner_contracts.py
COPY services/common/owner_effect_phase_map.py /app/src/common/owner_effect_phase_map.py
COPY services/common/platform_db.py /app/src/common/platform_db.py
COPY services/common/platform_errors.py /app/src/common/platform_errors.py
COPY services/common/runtime_annotations.py /app/src/common/runtime_annotations.py
COPY services/common/runtime_common.py /app/src/common/runtime_common.py
COPY services/common/runtime_policy_contracts.py /app/src/common/runtime_policy_contracts.py
COPY services/common/settings.py /app/src/common/settings.py
COPY services/common/tool_observability.py /app/src/common/tool_observability.py
COPY services/modules/__init__.py /app/src/modules/__init__.py
COPY services/modules/analysis/__init__.py /app/src/modules/analysis/__init__.py
COPY services/modules/analysis/a6_native.py /app/src/modules/analysis/a6_native.py
COPY services/modules/files/__init__.py /app/src/modules/files/__init__.py
COPY services/modules/files/_attachment_transport.py /app/src/modules/files/_attachment_transport.py
COPY services/modules/files/a14_read_witness.py /app/src/modules/files/a14_read_witness.py
COPY services/modules/files/a6_signed.py /app/src/modules/files/a6_signed.py
COPY services/modules/files/file_tools.py /app/src/modules/files/file_tools.py
COPY services/modules/files/models.py /app/src/modules/files/models.py
COPY services/modules/files/owner_backend.py /app/src/modules/files/owner_backend.py
COPY services/modules/files/project_explorer.py /app/src/modules/files/project_explorer.py
COPY services/modules/files/project_files.py /app/src/modules/files/project_files.py
COPY services/modules/files/project_workspace.py /app/src/modules/files/project_workspace.py
COPY services/modules/files/runtime.py /app/src/modules/files/runtime.py
COPY services/modules/files/workspace_ingress.py /app/src/modules/files/workspace_ingress.py
COPY services/modules/files/workspace_store.py /app/src/modules/files/workspace_store.py
COPY services/modules/project_runtime/__init__.py /app/src/modules/project_runtime/__init__.py
COPY services/modules/project_runtime/a11_owner_wire.py /app/src/modules/project_runtime/a11_owner_wire.py
COPY services/modules/project_runtime/a6_provider.py /app/src/modules/project_runtime/a6_provider.py
COPY services/modules/project_runtime/a6_runtime.py /app/src/modules/project_runtime/a6_runtime.py
COPY services/modules/project_runtime/a9_signed_lease.py /app/src/modules/project_runtime/a9_signed_lease.py
COPY services/modules/project_runtime/authorization.py /app/src/modules/project_runtime/authorization.py
COPY services/modules/project_runtime/catalog_metadata.py /app/src/modules/project_runtime/catalog_metadata.py
COPY services/modules/project_runtime/catalog_owner.py /app/src/modules/project_runtime/catalog_owner.py
COPY services/modules/project_runtime/integrations.py /app/src/modules/project_runtime/integrations.py
COPY services/modules/project_runtime/owner_authorization.py /app/src/modules/project_runtime/owner_authorization.py
COPY services/modules/project_runtime/owner_effects.py /app/src/modules/project_runtime/owner_effects.py
COPY services/modules/project_runtime/owner_status.py /app/src/modules/project_runtime/owner_status.py
COPY services/modules/project_runtime/owner_wire.py /app/src/modules/project_runtime/owner_wire.py
COPY services/modules/project_runtime/resource_query.py /app/src/modules/project_runtime/resource_query.py
COPY services/modules/project_runtime/resource_scope.py /app/src/modules/project_runtime/resource_scope.py
COPY services/modules/project_runtime/runtime_telemetry.py /app/src/modules/project_runtime/runtime_telemetry.py
COPY services/modules/project_runtime/variables.py /app/src/modules/project_runtime/variables.py
COPY services/modules/project_runtime/workspace_roots.py /app/src/modules/project_runtime/workspace_roots.py
COPY services/modules/workspace_compat/__init__.py /app/src/modules/workspace_compat/__init__.py
COPY services/modules/workspace_compat/legacy_store.py /app/src/modules/workspace_compat/legacy_store.py
# No installation of the Briareus project: source-only uv run.
COPY deploy/runtime_write_provenance.py /app/runtime_write_provenance.py
RUN python /app/runtime_write_provenance.py files
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
CMD ["uv", "run", "--frozen", "--no-sync", "--no-dev", "--project", "/app", "--directory", "/app/src", "python", "-m", "common.asgi"]
