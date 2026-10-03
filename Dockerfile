FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gosu netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project




FROM node:22-bookworm-slim AS chrome-devtools-mcp
RUN npm install --global --prefix /opt/chrome-devtools-mcp chrome-devtools-mcp@1.10.1

FROM oven/bun:1.4.2-alpine AS management-ui-build
WORKDIR /app
COPY frontend/package.json ./
RUN bun install
COPY frontend ./
RUN bun run build

FROM nginx:1.28-alpine AS management-ui
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=management-ui-build /app/dist /usr/share/nginx/html/admin
EXPOSE 8080
HEALTHCHECK --interval=2s --timeout=1s --start-period=1s --retries=10 \
    CMD ["wget", "-q", "-O", "-", "http://127.0.0.1:8080/health"]


FROM dependencies AS runtime-base

ARG BUILD_SHA=unknown
ARG BUILD_TIME=unknown

ENV FASTMCP_HOME=/auth \
    HOME=/home/bridge \
    BUILD_SHA=${BUILD_SHA} \
    BUILD_TIME=${BUILD_TIME}

COPY docker-entrypoint.sh /usr/local/bin/bridge-entrypoint
RUN chmod 0755 /usr/local/bin/bridge-entrypoint \
    && mkdir -p /auth /management /home/bridge \
    && chown -R 1000:1000 /auth /management /home/bridge

COPY src/common ./src/common

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD ["nc", "-z", "-w", "1", "127.0.0.1", "8000"]

ENTRYPOINT ["/usr/local/bin/bridge-entrypoint"]
CMD ["/app/.venv/bin/python", "-m", "common.asgi"]


FROM runtime-base AS auth
COPY src/auth_service ./src/auth_service
ENV ASGI_APP=auth_service.runtime:app


FROM runtime-base AS gateway
COPY src/bridge ./src/bridge
ENV ASGI_APP=bridge.server:app


FROM runtime-base AS management
COPY src/management ./src/management
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/files ./src/modules/files
ENV ASGI_APP=management.runtime:app \
    ASGI_FORWARDED_ALLOW_IPS=* \
    FILE_WORKSPACE_ROOT=/workspace


FROM runtime-base AS github
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/github ./src/modules/github
ENV ASGI_APP=modules.github.runtime:app


FROM runtime-base AS gitlab
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/gitlab ./src/modules/gitlab
ENV ASGI_APP=modules.gitlab.runtime:app


FROM runtime-base AS files
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/files ./src/modules/files
ENV ASGI_APP=modules.files.runtime:app \
    FILE_WORKSPACE_ROOT=/workspace


FROM runtime-base AS web
COPY --from=chrome-devtools-mcp /usr/local/bin/node /usr/local/bin/node
COPY --from=chrome-devtools-mcp /opt/chrome-devtools-mcp /opt/chrome-devtools-mcp
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/* \
    && uv sync --frozen --no-dev --group web --no-install-project
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/files ./src/modules/files
COPY src/modules/web ./src/modules/web
ENV ASGI_APP=modules.web.runtime:app \
    FILE_WORKSPACE_ROOT=/workspace \
    BROWSER_PROFILE_PATH=/browser/profile \
    BROWSER_EXECUTABLE_PATH=/usr/bin/chromium \
    BROWSER_DEVTOOLS_MCP_SCRIPT_PATH=/opt/chrome-devtools-mcp/lib/node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js \
    CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1 \
    CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1 \
    CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY=1 \
    XDG_CONFIG_HOME=/browser/config \
    XDG_CACHE_HOME=/browser/cache \
    BREAKPAD_DUMP_LOCATION=/browser/crash


FROM runtime-base AS terminal
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash build-essential sed git git-lfs gh openssh-client wget ripgrep findutils patch diffutils rsync jq \
        tar zip unzip gzip bzip2 xz-utils make gcc g++ binutils cmake ninja-build pkg-config \
        ccache autoconf automake libtool \
        python3-venv bc bison flex gawk gettext cpio file perl which libncurses-dev \
        procps psmisc lsof strace gdb iproute2 socat netcat-openbsd \
        picocom python3-serial \
    && rm -rf /var/lib/apt/lists/*
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/terminal ./src/modules/terminal
ENV ASGI_APP=modules.terminal.runtime:app \
    HOME=/home/agent \
    TERMINAL_WORKSPACE_ROOT=/workspace \
    TERMINAL_HOME=/home/agent


FROM runtime-base AS analysis
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/files ./src/modules/files
COPY src/modules/analysis ./src/modules/analysis
ENV ASGI_APP=modules.analysis.runtime:app \
    FILE_WORKSPACE_ROOT=/workspace


FROM runtime-base AS ghidra
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/ghidra ./src/modules/ghidra
ENV ASGI_APP=modules.ghidra.runtime:app


FROM runtime-base AS observability
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/signoz ./src/modules/signoz
COPY src/modules/coolify ./src/modules/coolify
COPY src/modules/observability ./src/modules/observability
ENV ASGI_APP=modules.observability.runtime:app


FROM gateway AS final
