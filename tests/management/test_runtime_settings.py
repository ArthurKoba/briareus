from __future__ import annotations

from pathlib import Path

from common.runtime_policy_contracts import McpRuntimePolicy, TerminalRuntimePolicy
from management.infrastructure.database import (
    Base,
    RuntimeSettingsRecord,
    create_database,
)
from management.infrastructure.repositories import SqlAlchemyRuntimeSettingsRepository


def test_runtime_settings_defaults_are_long_terminal_and_short_mcp(tmp_path: Path) -> None:
    engine, sessions = create_database(f"sqlite:///{tmp_path / 'runtime.sqlite3'}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyRuntimeSettingsRepository(sessions)

    terminal = repository.get_terminal_policy()
    mcp = repository.get_mcp_policy()

    assert terminal == TerminalRuntimePolicy(
        max_exec_timeout_seconds=21_600,
        max_job_runtime_seconds=43_200,
    )
    assert mcp == McpRuntimePolicy(call_timeout_seconds=5)
    engine.dispose()


def test_old_terminal_defaults_are_migrated_to_long_safety_caps(tmp_path: Path) -> None:
    engine, sessions = create_database(f"sqlite:///{tmp_path / 'runtime.sqlite3'}")
    Base.metadata.create_all(engine)
    with sessions.begin() as session:
        session.add(
            RuntimeSettingsRecord(
                id=1,
                terminal_max_exec_timeout_seconds=300,
                terminal_max_job_runtime_seconds=3600,
            )
        )

    repository = SqlAlchemyRuntimeSettingsRepository(sessions)
    policy = repository.get_terminal_policy()

    assert policy.max_exec_timeout_seconds == 21_600
    assert policy.max_job_runtime_seconds == 43_200
    engine.dispose()


def test_runtime_settings_persist_custom_mcp_timeout(tmp_path: Path) -> None:
    engine, sessions = create_database(f"sqlite:///{tmp_path / 'runtime.sqlite3'}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyRuntimeSettingsRepository(sessions)

    repository.save_mcp_policy(McpRuntimePolicy(call_timeout_seconds=17))

    assert repository.get_mcp_policy().call_timeout_seconds == 17
    engine.dispose()
