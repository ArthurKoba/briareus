# Briareus SVC: GitHub and GitLab are adapters of ONE version-control domain.
# This is a source-packaging target, NOT a public operation entrypoint.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app/services
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/common ./services/common
COPY services/modules/__init__.py ./services/modules/__init__.py
COPY services/modules/project_runtime ./services/modules/project_runtime
COPY services/modules/github ./services/modules/github
COPY services/modules/gitlab ./services/modules/gitlab
RUN useradd -u 1000 -m -d /home/svc svc
USER 1000:1000
EXPOSE 8000
# A real unified SVC ASGI runtime must be provided/reviewed by Runtime R9.
# Until then the container refuses to serve unapproved project tools.
CMD ["/bin/sh", "-ec", "echo BRIAREUS_SVC_UNIFIED_RUNTIME_PENDING >&2; exit 78"]
