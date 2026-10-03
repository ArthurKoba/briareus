from __future__ import annotations

from pathlib import Path

from common.models import JsonValue
from common.runtime_policy_contracts import (
    GitHubRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)
from management.application.services import RuntimeSettingsService
from management.infrastructure.database import (
    Base,
    RuntimeSettingsRecord,
    create_database,
)
from management.infrastructure.repositories import SqlAlchemyRuntimeSettingsRepository


class _MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, JsonValue] = {}

    def key(self, *parts: str) -> str:
        return ":".join(part.strip().casefold() for part in parts if part.strip())

    def get_json(self, key: str) -> JsonValue | None:
        return self.values.get(key)

    def set_json(self, key: str, value: object, *, ttl_seconds: int) -> bool:
        del ttl_seconds
        assert isinstance(value, (dict, list, str, int, float, bool)) or value is None
        self.values[key] = value
        return True

    def delete(self, *keys: str) -> bool:
        for key in keys:
            self.values.pop(key, None)
        return True


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
    github = repository.get_github_policy()
    assert github == GitHubRuntimePolicy(
        local_first_guidance=True,
        local_git_transport_enabled=False,
        remote_source_mutations_enabled=True,
    )
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


def test_runtime_settings_service_uses_and_refreshes_shared_cache(tmp_path: Path) -> None:
    engine, sessions = create_database(f"sqlite:///{tmp_path / 'runtime.sqlite3'}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyRuntimeSettingsRepository(sessions)
    cache = _MemoryCache()
    service = RuntimeSettingsService(repository, cache=cache)

    assert service.mcp_policy().call_timeout_seconds == 5
    repository.save_mcp_policy(McpRuntimePolicy(call_timeout_seconds=9))
    assert service.mcp_policy().call_timeout_seconds == 5

    service.update_mcp_policy(McpRuntimePolicy(call_timeout_seconds=17))
    assert service.mcp_policy().call_timeout_seconds == 17

    service.update_github_policy(
        GitHubRuntimePolicy(
            local_first_guidance=False,
            local_git_transport_enabled=True,
            remote_source_mutations_enabled=True,
        )
    )
    assert service.github_policy().local_git_transport_enabled is True

    service.update_terminal_policy(
        TerminalRuntimePolicy(max_exec_timeout_seconds=123, max_job_runtime_seconds=456)
    )
    assert service.terminal_policy().max_exec_timeout_seconds == 123
    assert service.terminal_policy().max_job_runtime_seconds == 456
    engine.dispose()
