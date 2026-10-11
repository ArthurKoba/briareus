FROM node:22-bookworm-slim AS chrome-devtools-mcp
RUN npm install --global --prefix /opt/chrome-devtools-mcp chrome-devtools-mcp@1.10.1

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY --from=chrome-devtools-mcp /usr/local/bin/node /usr/local/bin/node
COPY --from=chrome-devtools-mcp /opt/chrome-devtools-mcp /opt/chrome-devtools-mcp
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl chromium chromium-l10n fonts-liberation fonts-noto-color-emoji locales tzdata xvfb \
        libegl1 libgbm1 libgl1-mesa-dri libglx-mesa0 libva2 mesa-vulkan-drivers vainfo intel-media-va-driver \
    && sed -i 's/^# *\(ru_RU.UTF-8 UTF-8\)/\1/' /etc/locale.gen \
    && sed -i 's/^# *\(en_US.UTF-8 UTF-8\)/\1/' /etc/locale.gen \
    && locale-gen \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/web/uv-project/pyproject.toml /app/pyproject.toml
COPY deploy/web/uv-project/uv.lock /app/uv.lock
COPY deploy/web/uv-project/.python-version /app/.python-version
RUN --mount=type=cache,target=/root/.cache/uv,sharing=shared uv sync --frozen --no-dev --no-install-project
ENV ASGI_APP=modules.web.runtime:app \
    BROWSER_EXECUTABLE_PATH=/usr/bin/chromium \
    BROWSER_DEVTOOLS_MCP_SCRIPT_PATH=/opt/chrome-devtools-mcp/lib/node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js \
    CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1 \
    CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1 \
    CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY=1 \
    XDG_CONFIG_HOME=/browser/config \
    XDG_CACHE_HOME=/browser/cache \
    BREAKPAD_DUMP_LOCATION=/browser/crash
RUN useradd -u 1000 -m -d /home/bridge bridge \
    && mkdir -p /workspace /browser/profile /browser/config /browser/cache /browser/crash \
    && chown -R 1000:1000 /workspace /browser /home/bridge
# Source-only uv image: dependency layer cached above; selected service code
# remains uninstalled and runs directly via uv run --no-sync.
COPY services/common/__init__.py /app/src/common/__init__.py
COPY services/common/account_contracts.py /app/src/common/account_contracts.py
COPY services/common/admin_api_client.py /app/src/common/admin_api_client.py
COPY services/common/asgi.py /app/src/common/asgi.py
COPY services/common/audit_payloads.py /app/src/common/audit_payloads.py
COPY services/common/browser_remote_debug.py /app/src/common/browser_remote_debug.py
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
COPY services/common/websocket_proxy.py /app/src/common/websocket_proxy.py
COPY services/modules/__init__.py /app/src/modules/__init__.py
COPY services/modules/analysis/__init__.py /app/src/modules/analysis/__init__.py
COPY services/modules/analysis/a6_native.py /app/src/modules/analysis/a6_native.py
COPY services/modules/files/__init__.py /app/src/modules/files/__init__.py
COPY services/modules/files/_attachment_transport.py /app/src/modules/files/_attachment_transport.py
COPY services/modules/files/a14_read_witness.py /app/src/modules/files/a14_read_witness.py
COPY services/modules/files/a6_signed.py /app/src/modules/files/a6_signed.py
COPY services/modules/files/project_files.py /app/src/modules/files/project_files.py
COPY services/modules/files/project_workspace.py /app/src/modules/files/project_workspace.py
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
COPY services/modules/web/__init__.py /app/src/modules/web/__init__.py
COPY services/modules/web/browser.py /app/src/modules/web/browser.py
COPY services/modules/web/browser_extensions.py /app/src/modules/web/browser_extensions.py
COPY services/modules/web/browser_profile.py /app/src/modules/web/browser_profile.py
COPY services/modules/web/browser_tools.py /app/src/modules/web/browser_tools.py
COPY services/modules/web/curl_tools.py /app/src/modules/web/curl_tools.py
COPY services/modules/web/devtools_proxy.py /app/src/modules/web/devtools_proxy.py
COPY services/modules/web/errors.py /app/src/modules/web/errors.py
COPY services/modules/web/executor.py /app/src/modules/web/executor.py
COPY services/modules/web/external_browser_proxy.py /app/src/modules/web/external_browser_proxy.py
COPY services/modules/web/models.py /app/src/modules/web/models.py
COPY services/modules/web/operations.py /app/src/modules/web/operations.py
COPY services/modules/web/operator.py /app/src/modules/web/operator.py
COPY services/modules/web/presets.py /app/src/modules/web/presets.py
COPY services/modules/web/project_runtime.py /app/src/modules/web/project_runtime.py
COPY services/modules/web/request.py /app/src/modules/web/request.py
COPY services/modules/web/response.py /app/src/modules/web/response.py
COPY services/modules/web/runtime.py /app/src/modules/web/runtime.py
COPY services/modules/web/tools.py /app/src/modules/web/tools.py
COPY services/modules/workspace_compat/__init__.py /app/src/modules/workspace_compat/__init__.py
COPY services/modules/workspace_compat/legacy_store.py /app/src/modules/workspace_compat/legacy_store.py
# No installation of the Briareus project: source-only uv run.
COPY deploy/runtime_write_provenance.py /app/runtime_write_provenance.py
RUN python /app/runtime_write_provenance.py web
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
CMD ["uv", "run", "--frozen", "--no-sync", "--no-dev", "--project", "/app", "--directory", "/app/src", "python", "-m", "common.asgi"]
