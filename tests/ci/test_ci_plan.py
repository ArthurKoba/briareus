import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("ci_plan", Path("scripts/ci_plan.py"))
assert _SPEC is not None and _SPEC.loader is not None
ci_plan = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ci_plan
_SPEC.loader.exec_module(ci_plan)
plan = ci_plan.plan


def test_browser_change_is_targeted() -> None:
    result = plan(["src/modules/web/browser.py", "tests/modules/web/test_browser_tools.py"])
    assert result["full"] is False
    assert result["areas"] == ["web"]
    assert result["pytest_paths"] == ["tests/modules/web"]
    assert result["mypy_paths"] == ["src/modules/web"]
    assert result["frontend"] is False


def test_terminal_change_is_targeted() -> None:
    result = plan(["src/modules/terminal/manager.py"])
    assert result["full"] is False
    assert result["pytest_paths"] == ["tests/modules/terminal"]


def test_files_change_selects_files_validation() -> None:
    result = plan(["src/modules/files/workspace_store.py"])
    assert result["full"] is False
    assert result["pytest_paths"] == ["tests/modules/files"]
    assert result["mypy_paths"] == ["src/modules/files"]


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


def test_manual_full_gate_can_be_forced() -> None:
    result = plan(["src/modules/web/browser.py"], force_full=True)
    assert result["full"] is True


def test_main_push_uses_targeted_plan_by_default() -> None:
    result = plan(["src/modules/web/browser.py"])
    assert result["full"] is False
    assert result["pytest_paths"] == ["tests/modules/web"]


def test_docs_only_change_has_no_runtime_validation() -> None:
    result = plan(["README.md", "docs/OPERATIONS.md"])
    assert result["full"] is False
    assert result["areas"] == ["non-code"]
    assert result["pytest_paths"] == []


def test_unknown_source_change_escalates_to_full() -> None:
    result = plan(["src/new_service/runtime.py"])
    assert result["full"] is True


def test_frontend_change_selects_frontend_build_only() -> None:
    result = plan(["frontend/src/app/App.vue"])
    assert result["full"] is False
    assert result["areas"] == ["non-code"]
    assert result["pytest_paths"] == []
    assert result["frontend"] is True


def test_full_gate_includes_frontend_build() -> None:
    result = plan(["Dockerfile"])
    assert result["full"] is True
    assert result["frontend"] is True
