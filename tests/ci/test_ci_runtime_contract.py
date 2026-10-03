from pathlib import Path

import yaml


def test_ci_uses_one_substantive_runner_and_does_not_build_images() -> None:
    workflow_text = Path(".github/workflows/ci.yaml").read_text()
    workflow = yaml.safe_load(workflow_text)
    jobs = workflow["jobs"]

    assert set(jobs) == {"test", "docker"}
    assert "docker/build-push-action" not in workflow_text
    assert "docker/setup-buildx-action" not in workflow_text
    assert "docker-target:" not in workflow_text
    assert "docker compose config >/dev/null" in workflow_text
    assert "Build targeted CI plan" in workflow_text
    assert "uv sync --frozen" in workflow_text
    assert "uv run ruff check" in workflow_text
    assert "uv run mypy" in workflow_text
    assert "uv run pytest" in workflow_text

    docker_steps = jobs["docker"]["steps"]
    assert docker_steps == [{"run": "echo 'Production image build is owned by Coolify.'"}]


def test_compose_healthcheck_is_fast_but_tolerant() -> None:
    compose = Path("docker-compose.yaml").read_text()
    assert "interval: 2s" in compose
    assert "timeout: 1s" in compose
    assert "start_period: 2s" in compose
    assert "retries: 10" in compose
    assert "- nc" in compose
    assert "- -z" in compose
    assert "/app/.venv/bin/python" not in compose.split("x-management-client:", 1)[0]
