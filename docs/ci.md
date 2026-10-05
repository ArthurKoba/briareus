# Continuous integration

`mcp-bridge` is migrating CI execution from GitHub-hosted Actions runners to the shared
Jenkins service. Coolify remains the deployment/build authority; Jenkins does not build or
deploy production images.

## Validation contract

The repository-level `Jenkinsfile` owns CI validation:

1. checkout the branch/change request;
2. compute changed paths and call `scripts/ci_plan.py`;
3. run full backend `ruff`, `mypy` and unit tests in an ephemeral Python/uv container;
4. run PostgreSQL + Valkey integration only when the planner selects the authorization suite;
5. publish the GitHub check run named `validate`.

The Python dependency cache is persistent under the Jenkins home volume. Test containers,
PostgreSQL, Valkey and their per-build Docker network are disposable and removed after every
build.

## Deployment boundary

Jenkins stops at source validation. Successful merges/deployment-source changes are built and
rolled out by Coolify using the existing per-application watch paths and Dockerfile/Compose
contracts.

During migration, `.github/workflows/` remains as a fallback until one real Jenkins pull-request
build has passed and GitHub branch protection accepts the Jenkins `validate` check. Remove the
legacy Actions validation only after that acceptance is demonstrated.

## Security boundary

The shared Jenkins runner must not execute untrusted public-fork pull-request code. Public fork
changes should stay on GitHub-hosted runners or require an explicit trusted approval path before
being scheduled on the self-hosted Jenkins infrastructure.
