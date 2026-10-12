FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY services/infrastructure/gateway/pyproject.toml /app/pyproject.toml
COPY services/infrastructure/gateway/uv.lock /app/uv.lock
COPY services/infrastructure/gateway/.python-version /app/.python-version
RUN uv sync --frozen --no-dev --no-install-project
RUN useradd -u 1000 -m -d /home/bridge bridge
COPY services/infrastructure/gateway/src/ /app/src/
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
CMD ["uv", "run", "--frozen", "--no-sync", "--no-dev", "--project", "/app", "--directory", "/app/src", "uvicorn", "bridge.server:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1", "--no-access-log"]
