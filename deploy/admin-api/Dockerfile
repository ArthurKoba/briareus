FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app/services
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PYTHONPATH=/app/services:/app/services/admin-api/src \
    PLATFORM_ADMIN_PREVIEW_ENABLED=false
COPY services/common ./services/common
COPY services/authorization ./services/authorization
COPY services/identity ./services/identity
COPY services/teams ./services/teams
COPY services/projects ./services/projects
COPY services/agents ./services/agents
COPY services/admin-api/src ./services/admin-api/src
RUN useradd -u 1000 -m -d /home/platform platform
USER 1000:1000
EXPOSE 8000
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "platform_runtime:app", "--host", "127.0.0.1", "--port", "8000", "--no-proxy-headers"]
