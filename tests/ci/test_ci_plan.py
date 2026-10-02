import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("ci_plan", Path("scripts/ci_plan.py"))
assert _SPEC is not None and _SPEC.loader is not None
ci_plan = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ci_plan
_SPEC.loader.exec_module(ci_plan)
ALL_DOCKER_TARGETS = ci_plan.ALL_DOCKER_TARGETS
plan = ci_plan.plan


def test_browser_change_is_targeted() -> None:
    result = plan(["src/modules/curl/browser.py", "tests/modules/curl/test_browser_tools.py"])
    assert result["full"] is False
    assert result["areas"] == ["curl"]
    assert result["pytest_paths"] == ["tests/modules/curl"]
    assert result["mypy_paths"] == ["src/modules/curl"]
    assert result["docker_targets"] == ["curl"]


def test_terminal_change_is_targeted() -> None:
    result = plan(["src/modules/terminal/manager.py"])
    assert result["full"] is False
    assert result["pytest_paths"] == ["tests/modules/terminal"]
    assert result["docker_targets"] == ["terminal"]


def test_files_change_builds_dependent_images() -> None:
    result = plan(["src/modules/files/workspace_store.py"])
    assert result["full"] is False
    assert result["docker_targets"] == ["files", "management", "analysis", "curl"]


def test_shared_or_build_changes_force_full_gate() -> None:
    full_paths = (
        "src/common/settings.py",
        "pyproject.toml",
        "Dockerfile",
        ".github/workflows/ci.yaml",
        "scripts/ci_plan.py",
    )
    for path in full_paths:
        result = plan([path])
        assert result["full"] is True
        assert result["pytest_paths"] == ["tests"]
        assert result["docker_targets"] == list(ALL_DOCKER_TARGETS)


def test_main_push_can_force_full_gate() -> None:
    result = plan(["src/modules/curl/browser.py"], force_full=True)
    assert result["full"] is True


def test_docs_only_change_has_no_test_or_docker_work() -> None:
    result = plan(["README.md", "docs/OPERATIONS.md"])
    assert result["full"] is False
    assert result["areas"] == ["non-code"]
    assert result["pytest_paths"] == []
    assert result["docker_targets"] == []


def test_unknown_source_change_escalates_to_full() -> None:
    result = plan(["src/new_service/runtime.py"])
    assert result["full"] is True
