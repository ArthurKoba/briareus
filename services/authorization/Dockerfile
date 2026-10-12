FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY services/authorization/pyproject.toml /app/pyproject.toml
COPY services/authorization/uv.lock /app/uv.lock
COPY services/authorization/.python-version /app/.python-version
RUN --mount=type=cache,target=/root/.cache/uv,sharing=shared uv sync --frozen --no-dev --no-install-project
RUN useradd -u 1000 -m -d /home/briareus briareus
# Source-only uv image: dependency layer cached above; selected service code
# remains uninstalled and runs directly via uv run --no-sync.
COPY services/authorization/migrations/env.py /app/src/common/alembic_owners/access/env.py
COPY services/authorization/migrations/versions/0001_access_baseline.py /app/src/common/alembic_owners/access/versions/0001_access_baseline.py
# Keep the source within this independently deployable authorization folder.
# Older `services/common` is a transitional cross-service dependency pending
# migration to narrow shared/contracts; NEVER expose its ORM over HTTP.
COPY services/authorization/*.py /app/src/authorization/
COPY services/common/ /app/src/common/
# No installation of the Briareus project: source-only uv run.
COPY services/authorization/runtime_write_provenance.py /app/runtime_write_provenance.py
RUN python /app/runtime_write_provenance.py authorization
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
# Each service starts its OWN Alembic coordinator. Missing DB/grants fail closed.
CMD ["uv", "run", "--frozen", "--no-sync", "--no-dev", "--project", "/app", "--directory", "/app/src", "python", "-m", "uvicorn", "authorization.platform_runtime:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
