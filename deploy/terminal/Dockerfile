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
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash build-essential sed git git-lfs gh openssh-client wget ripgrep findutils patch diffutils rsync jq \
        tar zip unzip gzip bzip2 xz-utils make gcc g++ binutils cmake ninja-build pkg-config \
        ccache autoconf automake libtool python3-venv bc bison flex gawk gettext cpio file perl which libncurses-dev \
        procps psmisc lsof strace gdb iproute2 socat netcat-openbsd picocom python3-serial \
    && rm -rf /var/lib/apt/lists/*
ENV ASGI_APP=modules.terminal.runtime:app \
    HOME=/home/agent \
    TERMINAL_WORKSPACE_ROOT=/workspace \
    TERMINAL_HOME=/home/agent
COPY services/common ./services/common
COPY services/modules/__init__.py ./services/modules/__init__.py
COPY services/modules/project_runtime ./services/modules/project_runtime
COPY services/modules/terminal ./services/modules/terminal
RUN useradd -u 1000 -m -d /home/agent agent \
    && mkdir -p /workspace \
    && chown -R 1000:1000 /workspace /home/agent
USER 1000:1000
EXPOSE 8000
CMD ["/app/.venv/bin/python", "-m", "common.asgi"]
