from pathlib import Path


def test_ci_does_not_build_docker_images() -> None:
    workflow = Path(".github/workflows/ci.yaml").read_text()
    assert "docker/build-push-action" not in workflow
    assert "docker/setup-buildx-action" not in workflow
    assert "docker-target:" not in workflow
    assert "  docker:\n" in workflow
    assert "docker compose config >/dev/null" in workflow



def test_compose_healthcheck_is_fast_but_tolerant() -> None:
    compose = Path("docker-compose.yaml").read_text()
    assert "interval: 2s" in compose
    assert "timeout: 1s" in compose
    assert "start_period: 2s" in compose
    assert "retries: 10" in compose
    assert "socket.create_connection(('127.0.0.1', 8000), 0.5)" in compose
