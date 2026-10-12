FROM node:22-bookworm-slim AS chrome-devtools-mcp
RUN npm install --global --prefix /opt/chrome-devtools-mcp chrome-devtools-mcp@1.10.1

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY --from=chrome-devtools-mcp /usr/local/bin/node /usr/local/bin/node
COPY --from=chrome-devtools-mcp /opt/chrome-devtools-mcp /opt/chrome-devtools-mcp
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl chromium chromium-l10n fonts-liberation fonts-noto-color-emoji locales tzdata xvfb \
        libegl1 libgbm1 libgl1-mesa-dri libglx-mesa0 libva2 mesa-vulkan-drivers vainfo intel-media-va-driver \
    && sed -i 's/^# *\(ru_RU.UTF-8 UTF-8\)/\1/' /etc/locale.gen \
    && sed -i 's/^# *\(en_US.UTF-8 UTF-8\)/\1/' /etc/locale.gen \
    && locale-gen \
    && rm -rf /var/lib/apt/lists/*
COPY hands/web/pyproject.toml /app/pyproject.toml
COPY hands/web/uv.lock /app/uv.lock
COPY hands/web/.python-version /app/.python-version
RUN uv sync --frozen --no-dev --no-install-project
ENV BROWSER_EXECUTABLE_PATH=/usr/bin/chromium \
    BROWSER_DEVTOOLS_MCP_SCRIPT_PATH=/opt/chrome-devtools-mcp/lib/node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js \
    CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1 \
    CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1 \
    CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY=1 \
    XDG_CONFIG_HOME=/browser/config \
    XDG_CACHE_HOME=/browser/cache \
    BREAKPAD_DUMP_LOCATION=/browser/crash
RUN useradd -u 1000 -m -d /home/hand hand \
    && mkdir -p /workspace /browser/profile /browser/config /browser/cache /browser/crash \
    && chown -R 1000:1000 /workspace /browser /home/hand
COPY hands/web/src/ /app/src/
COPY shared/hand_runtime/ /app/src/hand_runtime/
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "web_hand.server:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
