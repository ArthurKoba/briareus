FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/admin-api/uv-project/pyproject.toml /app/pyproject.toml
COPY deploy/admin-api/uv-project/uv.lock /app/uv.lock
COPY deploy/admin-api/uv-project/.python-version /app/.python-version
RUN --mount=type=cache,target=/root/.cache/uv,sharing=shared uv sync --frozen --no-dev --no-install-project
RUN useradd -u 1000 -m -d /home/platform platform
# Source-only uv image: dependency layer cached above; selected service code
# remains uninstalled and runs directly via uv run --no-sync.
COPY services/admin-api/src/platform_runtime.py /app/src/platform_runtime.py
# No installation of the Briareus project: source-only uv run.
COPY deploy/runtime_write_provenance.py /app/runtime_write_provenance.py
RUN python /app/runtime_write_provenance.py admin-api
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
CMD ["uv", "run", "--frozen", "--no-sync", "--no-dev", "--project", "/app", "--directory", "/app/src", "python", "-m", "uvicorn", "platform_runtime:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
