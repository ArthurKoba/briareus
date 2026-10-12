FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/gateway/uv-project/pyproject.toml /app/pyproject.toml
COPY deploy/gateway/uv-project/uv.lock /app/uv.lock
COPY deploy/gateway/uv-project/.python-version /app/.python-version
RUN --mount=type=cache,target=/root/.cache/uv,sharing=shared uv sync --frozen --no-dev --no-install-project
ENV ASGI_APP=bridge.server:static_app
RUN useradd -u 1000 -m -d /home/bridge bridge
# Source-only uv image: dependency layer cached above; selected service code
# remains uninstalled and runs directly via uv run --no-sync.
COPY services/bridge/__init__.py /app/src/bridge/__init__.py
COPY services/bridge/server.py /app/src/bridge/server.py
COPY services/bridge/gateway_transport.py /app/src/bridge/gateway_transport.py
COPY services/bridge/single_origin.py /app/src/bridge/single_origin.py
COPY services/common/__init__.py /app/src/common/__init__.py
COPY services/common/account_contracts.py /app/src/common/account_contracts.py
COPY services/common/admin_api_client.py /app/src/common/admin_api_client.py
COPY services/common/asgi.py /app/src/common/asgi.py
COPY services/common/cache.py /app/src/common/cache.py
COPY services/common/http_transport.py /app/src/common/http_transport.py
COPY services/common/models.py /app/src/common/models.py
COPY services/common/oauth_session_contracts.py /app/src/common/oauth_session_contracts.py
COPY services/common/observability.py /app/src/common/observability.py
COPY services/common/runtime_policy_contracts.py /app/src/common/runtime_policy_contracts.py
COPY services/common/settings.py /app/src/common/settings.py
COPY services/modules/__init__.py /app/src/modules/__init__.py
COPY services/modules/project_runtime/__init__.py /app/src/modules/project_runtime/__init__.py
COPY services/modules/project_runtime/runtime_telemetry.py /app/src/modules/project_runtime/runtime_telemetry.py
# No installation of the Briareus project: source-only uv run.
COPY deploy/runtime_write_provenance.py /app/runtime_write_provenance.py
RUN python /app/runtime_write_provenance.py gateway
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
CMD ["uv", "run", "--frozen", "--no-sync", "--no-dev", "--project", "/app", "--directory", "/app/src", "python", "-m", "common.asgi"]
