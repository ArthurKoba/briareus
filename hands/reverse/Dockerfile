FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY hands/reverse/pyproject.toml /app/pyproject.toml
COPY hands/reverse/uv.lock /app/uv.lock
COPY hands/reverse/.python-version /app/.python-version
RUN uv sync --frozen --no-dev --no-install-project
RUN useradd -u 1000 -m -d /home/hand hand
COPY hands/reverse/src/ /app/src/
COPY shared/hand_runtime/ /app/src/hand_runtime/
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "reverse_hand.server:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
