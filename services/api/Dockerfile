FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY services/api/pyproject.toml services/api/uv.lock /app/
RUN --mount=type=cache,target=/root/.cache/uv,sharing=shared uv sync --frozen --no-dev --no-install-project
RUN useradd -u 1000 -m -d /home/control-panel control-panel
COPY services/api/src/ /app/src/
USER 1000:1000
WORKDIR /app/src
EXPOSE 8000
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "control_panel_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
