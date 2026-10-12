FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*
COPY hands/svc/pyproject.toml /app/pyproject.toml
COPY hands/svc/uv.lock /app/uv.lock
COPY hands/svc/.python-version /app/.python-version
RUN uv sync --frozen --no-dev --no-install-project
RUN useradd -u 1000 -m -d /home/svc svc
COPY hands/svc/src/ /app/src/
COPY shared/hand_runtime/ /app/src/hand_runtime/
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "svc_hand.server:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
