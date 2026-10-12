FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/admin-api/uv-project/pyproject.toml /app/pyproject.toml
COPY deploy/admin-api/uv-project/uv.lock /app/uv.lock
COPY deploy/admin-api/uv-project/.python-version /app/.python-version
RUN --mount=type=cache,target=/root/.cache/uv,sharing=shared uv sync --frozen --no-dev --no-install-project
RUN useradd -u 1000 -m -d /home/platform platform
# Source-only uv image: dependency layer cached above; selected service code
# remains uninstalled and runs directly via uv run --no-sync.
COPY services/admin-api/src/identity_http_contracts.py /app/src/identity_http_contracts.py
COPY services/admin-api/src/platform_runtime.py /app/src/platform_runtime.py
COPY services/admin-api/src/presentation/__init__.py /app/src/presentation/__init__.py
COPY services/admin-api/src/presentation/first_user_http.py /app/src/presentation/first_user_http.py
COPY services/admin-api/src/presentation/owner_bff_evidence.py /app/src/presentation/owner_bff_evidence.py
COPY services/admin-api/src/presentation/owner_bff_private_handlers.py /app/src/presentation/owner_bff_private_handlers.py
COPY services/admin-api/src/presentation/private_c2_api.py /app/src/presentation/private_c2_api.py
COPY services/admin-api/src/presentation/private_c2_views.py /app/src/presentation/private_c2_views.py
COPY services/common/__init__.py /app/src/common/__init__.py
COPY services/common/owner_bff_models.py /app/src/common/owner_bff_models.py
COPY services/common/owner_bff_signed.py /app/src/common/owner_bff_signed.py
COPY services/common/owner_contracts.py /app/src/common/owner_contracts.py
COPY services/common/platform_db.py /app/src/common/platform_db.py
COPY services/common/platform_errors.py /app/src/common/platform_errors.py
COPY services/common/private_user_token.py /app/src/common/private_user_token.py
COPY services/common/settings.py /app/src/common/settings.py
# No installation of the Briareus project: source-only uv run.
COPY deploy/runtime_write_provenance.py /app/runtime_write_provenance.py
RUN python /app/runtime_write_provenance.py admin-api
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
CMD ["uv", "run", "--frozen", "--no-sync", "--no-dev", "--project", "/app", "--directory", "/app/src", "python", "-m", "uvicorn", "platform_runtime:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
