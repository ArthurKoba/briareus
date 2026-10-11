FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/svc/uv-project/pyproject.toml /app/pyproject.toml
COPY deploy/svc/uv-project/uv.lock /app/uv.lock
COPY deploy/svc/uv-project/.python-version /app/.python-version
RUN --mount=type=cache,target=/root/.cache/uv,sharing=shared uv sync --frozen --no-dev --no-install-project
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -u 1000 -m -d /home/svc svc
# Source-only uv image: dependency layer cached above; selected service code
# remains uninstalled and runs directly via uv run --no-sync.
COPY services/common/__init__.py /app/src/common/__init__.py
COPY services/common/account_contracts.py /app/src/common/account_contracts.py
COPY services/common/admin_api_client.py /app/src/common/admin_api_client.py
COPY services/common/asgi.py /app/src/common/asgi.py
COPY services/common/audit_payloads.py /app/src/common/audit_payloads.py
COPY services/common/cache.py /app/src/common/cache.py
COPY services/common/git/__init__.py /app/src/common/git/__init__.py
COPY services/common/git/policy.py /app/src/common/git/policy.py
COPY services/common/http_transport.py /app/src/common/http_transport.py
COPY services/common/models.py /app/src/common/models.py
COPY services/common/oauth_session_contracts.py /app/src/common/oauth_session_contracts.py
COPY services/common/observability.py /app/src/common/observability.py
COPY services/common/repository_checkout.py /app/src/common/repository_checkout.py
COPY services/common/runtime_annotations.py /app/src/common/runtime_annotations.py
COPY services/common/runtime_common.py /app/src/common/runtime_common.py
COPY services/common/runtime_policy_contracts.py /app/src/common/runtime_policy_contracts.py
COPY services/common/settings.py /app/src/common/settings.py
COPY services/common/tool_observability.py /app/src/common/tool_observability.py
COPY services/modules/__init__.py /app/src/modules/__init__.py
COPY services/modules/github/__init__.py /app/src/modules/github/__init__.py
COPY services/modules/github/account_tools.py /app/src/modules/github/account_tools.py
COPY services/modules/github/actions_diagnostics.py /app/src/modules/github/actions_diagnostics.py
COPY services/modules/github/actions_mutations.py /app/src/modules/github/actions_mutations.py
COPY services/modules/github/base.py /app/src/modules/github/base.py
COPY services/modules/github/content_api.py /app/src/modules/github/content_api.py
COPY services/modules/github/content_tools.py /app/src/modules/github/content_tools.py
COPY services/modules/github/contents.py /app/src/modules/github/contents.py
COPY services/modules/github/git_mutations.py /app/src/modules/github/git_mutations.py
COPY services/modules/github/git_transaction.py /app/src/modules/github/git_transaction.py
COPY services/modules/github/github_actions.py /app/src/modules/github/github_actions.py
COPY services/modules/github/github_actions_tools.py /app/src/modules/github/github_actions_tools.py
COPY services/modules/github/github_admin.py /app/src/modules/github/github_admin.py
COPY services/modules/github/github_agent.py /app/src/modules/github/github_agent.py
COPY services/modules/github/github_collab.py /app/src/modules/github/github_collab.py
COPY services/modules/github/github_collab_tools.py /app/src/modules/github/github_collab_tools.py
COPY services/modules/github/github_core_tools.py /app/src/modules/github/github_core_tools.py
COPY services/modules/github/github_history.py /app/src/modules/github/github_history.py
COPY services/modules/github/github_history_graph.py /app/src/modules/github/github_history_graph.py
COPY services/modules/github/github_identity.py /app/src/modules/github/github_identity.py
COPY services/modules/github/github_review.py /app/src/modules/github/github_review.py
COPY services/modules/github/github_review_tools.py /app/src/modules/github/github_review_tools.py
COPY services/modules/github/github_reviewer_tools.py /app/src/modules/github/github_reviewer_tools.py
COPY services/modules/github/github_tools.py /app/src/modules/github/github_tools.py
COPY services/modules/github/github_workflow.py /app/src/modules/github/github_workflow.py
COPY services/modules/github/history_projection.py /app/src/modules/github/history_projection.py
COPY services/modules/github/issue_tools.py /app/src/modules/github/issue_tools.py
COPY services/modules/github/issues.py /app/src/modules/github/issues.py
COPY services/modules/github/models.py /app/src/modules/github/models.py
COPY services/modules/github/policy.py /app/src/modules/github/policy.py
COPY services/modules/github/pull_tools.py /app/src/modules/github/pull_tools.py
COPY services/modules/github/pulls.py /app/src/modules/github/pulls.py
COPY services/modules/github/ref_tools.py /app/src/modules/github/ref_tools.py
COPY services/modules/github/refs.py /app/src/modules/github/refs.py
COPY services/modules/github/run_tools.py /app/src/modules/github/run_tools.py
COPY services/modules/github/runs.py /app/src/modules/github/runs.py
COPY services/modules/github/runtime.py /app/src/modules/github/runtime.py
COPY services/modules/github/tool_context.py /app/src/modules/github/tool_context.py
COPY services/modules/github/workflow_guard.py /app/src/modules/github/workflow_guard.py
COPY services/modules/gitlab/__init__.py /app/src/modules/gitlab/__init__.py
COPY services/modules/gitlab/api.py /app/src/modules/gitlab/api.py
COPY services/modules/gitlab/errors.py /app/src/modules/gitlab/errors.py
COPY services/modules/gitlab/gitlab_client.py /app/src/modules/gitlab/gitlab_client.py
COPY services/modules/gitlab/gitlab_tools.py /app/src/modules/gitlab/gitlab_tools.py
COPY services/modules/gitlab/issue_tools.py /app/src/modules/gitlab/issue_tools.py
COPY services/modules/gitlab/issues.py /app/src/modules/gitlab/issues.py
COPY services/modules/gitlab/merge_request_tools.py /app/src/modules/gitlab/merge_request_tools.py
COPY services/modules/gitlab/merge_requests.py /app/src/modules/gitlab/merge_requests.py
COPY services/modules/gitlab/models.py /app/src/modules/gitlab/models.py
COPY services/modules/gitlab/pipeline_tools.py /app/src/modules/gitlab/pipeline_tools.py
COPY services/modules/gitlab/pipelines.py /app/src/modules/gitlab/pipelines.py
COPY services/modules/gitlab/policy.py /app/src/modules/gitlab/policy.py
COPY services/modules/gitlab/profile_tools.py /app/src/modules/gitlab/profile_tools.py
COPY services/modules/gitlab/projects.py /app/src/modules/gitlab/projects.py
COPY services/modules/gitlab/repository.py /app/src/modules/gitlab/repository.py
COPY services/modules/gitlab/repository_tools.py /app/src/modules/gitlab/repository_tools.py
COPY services/modules/gitlab/runtime.py /app/src/modules/gitlab/runtime.py
COPY services/modules/gitlab/tool_context.py /app/src/modules/gitlab/tool_context.py
COPY services/modules/gitlab/workflow_guard.py /app/src/modules/gitlab/workflow_guard.py
COPY services/modules/project_runtime/__init__.py /app/src/modules/project_runtime/__init__.py
COPY services/modules/project_runtime/authorization.py /app/src/modules/project_runtime/authorization.py
COPY services/modules/project_runtime/runtime_telemetry.py /app/src/modules/project_runtime/runtime_telemetry.py
COPY services/modules/svc/__init__.py /app/src/modules/svc/__init__.py
COPY services/modules/svc/composition.py /app/src/modules/svc/composition.py
COPY services/modules/svc/runtime.py /app/src/modules/svc/runtime.py
# No installation of the Briareus project: source-only uv run.
COPY deploy/runtime_write_provenance.py /app/runtime_write_provenance.py
RUN python /app/runtime_write_provenance.py svc
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
CMD ["uv", "run", "--frozen", "--no-sync", "--no-dev", "--project", "/app", "--directory", "/app/src", "python", "-m", "uvicorn", "modules.svc.runtime:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
