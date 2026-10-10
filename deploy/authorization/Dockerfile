# D4 staged: valid only after independent A10 acceptance and publication.
# The Briareus wheel, not the source tree on PYTHONPATH, owns normal
# Authorization startup and its immutable packaged Alembic revision graph.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/authorization ./services/authorization
COPY services/common ./services/common
COPY services/identity ./services/identity
COPY services/teams ./services/teams
COPY services/projects ./services/projects
COPY services/agents ./services/agents
COPY services/bridge ./services/bridge
COPY services/modules ./services/modules
COPY services/admin-api/src/presentation ./services/admin-api/src/presentation
COPY services/admin-api/src/platform_runtime.py ./services/admin-api/src/platform_runtime.py
COPY services/admin-api/src/api_errors.py ./services/admin-api/src/api_errors.py
COPY scripts/alembic.ini ./scripts/alembic.ini
COPY scripts/alembic_greenfield ./scripts/alembic_greenfield
# Install the source-tracked, non-editable Briareus wheel with bundled
# Alembic revisions. OTel service.version resolves from this distribution.
RUN uv sync --frozen --no-dev --no-editable
RUN /app/.venv/bin/python -c "from importlib.metadata import version; from authorization.schema_migrations import _config; assert version('briareus') != 'unknown'; assert len(_config().get_main_option('script_location')) > 0"
RUN useradd -u 1000 -m -d /home/briareus briareus
USER 1000:1000
EXPOSE 8000
# Normal app lifespan acquires the PostgreSQL advisory lock, applies
# only reviewed Alembic revisions and refuses readiness without C2 trust.
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "authorization.platform_runtime:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
