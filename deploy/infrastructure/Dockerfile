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
ENV ASGI_APP=modules.observability.runtime:app
COPY services/common ./services/common
COPY services/modules/__init__.py ./services/modules/__init__.py
COPY services/modules/project_runtime ./services/modules/project_runtime
COPY services/modules/signoz ./services/modules/signoz
COPY services/modules/coolify ./services/modules/coolify
COPY services/modules/observability ./services/modules/observability
RUN useradd -u 1000 -m -d /home/bridge bridge
USER 1000:1000
EXPOSE 8000
CMD ["/app/.venv/bin/python", "-m", "common.asgi"]
