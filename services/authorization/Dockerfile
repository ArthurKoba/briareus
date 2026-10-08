# Build from the repository root, even though this Dockerfile belongs to Auth.
# The context is shared only for the lockfile and the common Python library.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app/services \
    HOME=/home/bridge \
    FASTMCP_HOME=/authorization \
    ASGI_APP=authorization.runtime:app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/common ./services/common
COPY services/authorization ./services/authorization

RUN mkdir -p /authorization /home/bridge \
    && chown -R 1000:1000 /authorization /home/bridge

USER 1000:1000
EXPOSE 8000
CMD ["/app/.venv/bin/python", "-m", "common.asgi"]
