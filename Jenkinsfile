pipeline {
    agent any

    options {
        disableConcurrentBuilds(abortPrevious: true)
        skipDefaultCheckout(true)
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
    }

    environment {
        CI_IMAGE = 'ghcr.io/astral-sh/uv:0.8.22-python3.14-bookworm-slim'
    }

    stages {
        stage('Checkout') {
            steps {
                deleteDir()
                checkout scm
                publishChecks(
                    name: 'validate',
                    title: 'Jenkins CI',
                    summary: 'Backend validation is running.',
                    detailsURL: env.BUILD_URL,
                    status: 'IN_PROGRESS',
                    conclusion: 'NONE'
                )
            }
        }

        stage('Plan') {
            steps {
                sh '''#!/usr/bin/env bash
set -euo pipefail

mkdir -p "$JENKINS_HOME/caches/uv"

if [[ -n "${CHANGE_TARGET:-}" ]]; then
    git fetch --no-tags origin "+refs/heads/${CHANGE_TARGET}:refs/remotes/origin/${CHANGE_TARGET}"
    git diff --name-only "origin/${CHANGE_TARGET}...HEAD" > .ci-changed-paths
elif [[ -n "${GIT_PREVIOUS_COMMIT:-}" ]] && git cat-file -e "${GIT_PREVIOUS_COMMIT}^{commit}" 2>/dev/null; then
    git diff --name-only "${GIT_PREVIOUS_COMMIT}...HEAD" > .ci-changed-paths
elif git rev-parse HEAD^ >/dev/null 2>&1; then
    git diff --name-only HEAD^ HEAD > .ci-changed-paths
else
    : > .ci-changed-paths
fi

docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp/ci-home \
    -v "$WORKSPACE:/workspace" \
    -w /workspace \
    "$CI_IMAGE" \
    python scripts/ci_plan.py --paths-file .ci-changed-paths > .ci-plan.json

cat .ci-plan.json
rm -f .ci-run-authorization-integration
if grep -q '"run_authorization_integration": true' .ci-plan.json; then
    touch .ci-run-authorization-integration
fi
'''
            }
        }

        stage('Validate') {
            steps {
                sh '''#!/usr/bin/env bash
set -euo pipefail

mkdir -p "$JENKINS_HOME/caches/uv"

docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp/ci-home \
    -e UV_CACHE_DIR=/ci-cache/uv \
    -v "$WORKSPACE:/workspace" \
    -v "$JENKINS_HOME/caches/uv:/ci-cache/uv" \
    -w /workspace \
    "$CI_IMAGE" \
    sh -lc '\
        uv sync --frozen --dev --no-install-project && \
        .venv/bin/ruff check services tests scripts && \
        .venv/bin/mypy services/authorization services/bridge services/common services/admin-api/src scripts/provision_authorization_database.py scripts/ci_plan.py && \
        PYTHONPATH=services .venv/bin/python -m unittest discover -s tests -v\
    '
'''
            }
        }

        stage('Authorization integration') {
            when {
                expression { fileExists('.ci-run-authorization-integration') }
            }
            steps {
                sh '''#!/usr/bin/env bash
set -euo pipefail

suffix="$(printf '%s' "$BUILD_TAG" | tr -cs '[:alnum:]_.-' '-')"
network="ci-${suffix}"
postgres="ci-postgres-${suffix}"
valkey="ci-valkey-${suffix}"

# A prior interrupted build may have left names behind.
docker rm -f "$postgres" "$valkey" >/dev/null 2>&1 || true
docker network rm "$network" >/dev/null 2>&1 || true

docker network create "$network" >/dev/null

docker run -d --name "$postgres" --network "$network" --network-alias postgres \
    -e POSTGRES_DB=postgres \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=postgres \
    --health-cmd='pg_isready -U postgres -d postgres' \
    --health-interval=2s \
    --health-timeout=2s \
    --health-retries=20 \
    postgres:18.6-alpine >/dev/null

docker run -d --name "$valkey" --network "$network" --network-alias valkey \
    --health-cmd='valkey-cli ping' \
    --health-interval=2s \
    --health-timeout=2s \
    --health-retries=20 \
    valkey/valkey:9.1.2-alpine >/dev/null

for container in "$postgres" "$valkey"; do
    for _ in $(seq 1 30); do
        status="$(docker inspect --format '{{.State.Health.Status}}' "$container")"
        [[ "$status" == healthy ]] && break
        [[ "$status" == unhealthy ]] && { docker logs "$container"; exit 1; }
        sleep 2
    done
    [[ "$(docker inspect --format '{{.State.Health.Status}}' "$container")" == healthy ]] || {
        docker logs "$container"
        exit 1
    }
done

mkdir -p "$JENKINS_HOME/caches/uv"

docker run --rm \
    --user "$(id -u):$(id -g)" \
    --network "$network" \
    -e HOME=/tmp/ci-home \
    -e UV_CACHE_DIR=/ci-cache/uv \
    -e POSTGRES_HOST=postgres \
    -e POSTGRES_PORT=5432 \
    -e POSTGRES_DB=postgres \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=postgres \
    -e AUTHORIZATION_POSTGRES_DB=authorization_mvp \
    -e AUTHORIZATION_POSTGRES_USER=authorization_mvp \
    -e AUTHORIZATION_POSTGRES_PASSWORD=authorization_mvp_secret \
    -e TEST_POSTGRES_HOST=postgres \
    -e TEST_POSTGRES_PORT=5432 \
    -e TEST_AUTHORIZATION_POSTGRES_DB=authorization_mvp \
    -e TEST_AUTHORIZATION_POSTGRES_USER=authorization_mvp \
    -e TEST_AUTHORIZATION_POSTGRES_PASSWORD=authorization_mvp_secret \
    -e TEST_VALKEY_URL=redis://valkey:6379/15 \
    -v "$WORKSPACE:/workspace" \
    -v "$JENKINS_HOME/caches/uv:/ci-cache/uv" \
    -w /workspace \
    "$CI_IMAGE" \
    sh -lc '\
        uv sync --frozen --dev --no-install-project && \
        .venv/bin/python scripts/provision_authorization_database.py && \
        PYTHONPATH=services .venv/bin/python -m unittest tests.test_postgres_authorization_access -v\
    '
'''
            }
        }
    }

    post {
        success {
            publishChecks(
                name: 'validate',
                title: 'Jenkins CI',
                summary: 'Backend validation passed.',
                detailsURL: env.BUILD_URL,
                status: 'COMPLETED',
                conclusion: 'SUCCESS'
            )
        }
        failure {
            publishChecks(
                name: 'validate',
                title: 'Jenkins CI',
                summary: 'Backend validation failed. See Jenkins for details.',
                detailsURL: env.BUILD_URL,
                status: 'COMPLETED',
                conclusion: 'FAILURE'
            )
        }
        aborted {
            publishChecks(
                name: 'validate',
                title: 'Jenkins CI',
                summary: 'Backend validation was canceled.',
                detailsURL: env.BUILD_URL,
                status: 'COMPLETED',
                conclusion: 'CANCELED'
            )
        }
        cleanup {
            sh '''#!/usr/bin/env bash
set +e
suffix="$(printf '%s' "$BUILD_TAG" | tr -cs '[:alnum:]_.-' '-')"
docker rm -f "ci-postgres-${suffix}" "ci-valkey-${suffix}" >/dev/null 2>&1
docker network rm "ci-${suffix}" >/dev/null 2>&1
'''
            deleteDir()
        }
    }
}
