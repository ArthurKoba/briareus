from __future__ import annotations

from typing import Any

import pytest

from management.infrastructure.reverse import ReverseAdminClient


class FakeReverseAdminClient(ReverseAdminClient):
    def __init__(self, responses: dict[str, Any]) -> None:
        super().__init__("http://unused")
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def _call(self, tool: str, arguments=None):
        args = dict(arguments or {})
        self.calls.append((tool, args))
        value = self.responses[tool]
        if isinstance(value, list):
            return value.pop(0)
        return value


@pytest.mark.asyncio
async def test_reverse_overview_links_projects_to_workers() -> None:
    client = FakeReverseAdminClient(
        {
            "list_projects": {
                "worker_count": 2,
                "workers": [
                    {
                        "worker_index": 0,
                        "project_id": "ghp_alpha",
                        "project_name": "alpha",
                        "queued": 2,
                        "running": True,
                    },
                    {
                        "worker_index": 1,
                        "project_id": None,
                        "project_name": None,
                        "queued": 0,
                        "running": False,
                    },
                ],
                "projects": [
                    {
                        "project_id": "ghp_alpha",
                        "name": "alpha",
                        "path": "/projects/alpha.gpr",
                        "session": "active",
                    },
                    {
                        "project_id": "ghp_beta",
                        "name": "beta",
                        "path": "/projects/beta.gpr",
                        "session": "available",
                    },
                ],
            }
        }
    )

    overview = await client.overview()

    projects = overview["projects"]
    assert isinstance(projects, list)
    assert projects[0]["worker_index"] == 0
    assert projects[0]["group"] == "Root"
    assert projects[1]["worker_index"] is None
    assert projects[1]["group"] == "Root"


@pytest.mark.asyncio
async def test_reverse_open_programs_normalizes_backend_shapes() -> None:
    client = FakeReverseAdminClient(
        {"list_open_programs": {"programs": ["a.bin", {"name": "b.bin", "open": True}]}}
    )

    programs = await client.open_programs("ghp_alpha")

    assert programs == ["a.bin", {"name": "b.bin", "open": True}]


@pytest.mark.asyncio
async def test_reverse_worker_and_project_actions_use_backend_tools() -> None:
    client = FakeReverseAdminClient(
        {
            "create_project": {"project_id": "ghp_new", "name": "new"},
            "delete_project": {"project_id": "ghp_new", "deleted": True},
            "set_worker_enabled": {"worker_index": 1, "enabled": False},
        }
    )

    await client.create_project("new", "/projects/group")
    await client.delete_project("ghp_new")
    await client.set_worker_enabled(1, False)

    assert client.calls == [
        (
            "create_project",
            {"name": "new", "parent_dir": "/projects/group"},
        ),
        ("delete_project", {"project_id": "ghp_new"}),
        (
            "set_worker_enabled",
            {
                "worker_index": 1,
                "enabled": False,
                "close_project": True,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_reverse_coverage_aggregates_real_completeness_scores() -> None:
    client = FakeReverseAdminClient(
        {
            "get_function_count": {"function_count": 4},
            "list_functions_enhanced": {
                "functions": [
                    {"address": "1000", "name": "A"},
                    {"address": "1010", "name": "B"},
                    {"address": "1020", "name": "C"},
                    {"address": "1030", "name": "D"},
                ]
            },
            "analyze_function_completeness": {
                "results": [
                    {
                        "effective_score": 90,
                        "completeness_score": 85,
                        "has_custom_name": True,
                        "has_plate_comment": True,
                        "has_prototype": True,
                        "return_type_resolved": True,
                    },
                    {
                        "effective_score": 70,
                        "completeness_score": 65,
                        "has_custom_name": True,
                        "has_plate_comment": False,
                        "has_prototype": True,
                        "return_type_resolved": True,
                    },
                    {
                        "effective_score": 50,
                        "completeness_score": 45,
                        "has_custom_name": False,
                        "has_plate_comment": False,
                        "has_prototype": True,
                        "return_type_resolved": False,
                    },
                    {
                        "effective_score": 20,
                        "completeness_score": 15,
                        "has_custom_name": False,
                        "has_plate_comment": False,
                        "has_prototype": False,
                        "return_type_resolved": False,
                    },
                ]
            },
        }
    )

    coverage = await client.coverage(
        "ghp_alpha",
        "program.bin",
        full=True,
    )

    assert coverage["total_functions"] == 4
    assert coverage["evaluated_functions"] == 4
    assert coverage["approximate"] is False
    assert coverage["average_effective_score"] == 57.5
    assert coverage["complete_80_plus_percent"] == 25.0
    assert coverage["strong_60_79_percent"] == 25.0
    assert coverage["partial_40_59_percent"] == 25.0
    assert coverage["low_under_40_percent"] == 25.0
    assert coverage["custom_named"] == 2
    assert coverage["plate_documented"] == 1
    assert coverage["prototype_set"] == 3
    assert coverage["return_type_resolved"] == 2


@pytest.mark.asyncio
async def test_reverse_quick_coverage_marks_large_program_approximate() -> None:
    functions = [
        {"address": f"{index:04x}", "name": f"F{index}"}
        for index in range(10)
    ]
    client = FakeReverseAdminClient(
        {
            "get_function_count": {"function_count": 10},
            "list_functions_enhanced": {"functions": functions},
            "analyze_function_completeness": [
                {
                    "results": [
                        {
                            "effective_score": 80,
                            "completeness_score": 80,
                        }
                        for _ in range(2)
                    ]
                },
                {
                    "results": [
                        {
                            "effective_score": 80,
                            "completeness_score": 80,
                        }
                        for _ in range(2)
                    ]
                },
            ],
        }
    )

    coverage = await client.coverage(
        "ghp_alpha",
        "program.bin",
        full=False,
        sample_size=4,
        batch_size=2,
    )

    assert coverage["approximate"] is True
    assert coverage["sample_size"] == 4
    assert coverage["evaluated_functions"] == 4
    assert coverage["complete_80_plus_percent"] == 100.0


@pytest.mark.asyncio
async def test_reverse_session_settings_use_private_backend_tools() -> None:
    client = FakeReverseAdminClient(
        {
            "project_session_settings": {
                "idle_timeout_seconds": 900.0,
                "auto_release_enabled": True,
            },
            "set_project_idle_timeout": {
                "idle_timeout_seconds": 120.0,
                "auto_release_enabled": True,
            },
        }
    )

    current = await client.session_settings()
    updated = await client.set_idle_timeout(120)

    assert current["idle_timeout_seconds"] == 900.0
    assert updated["idle_timeout_seconds"] == 120.0
    assert client.calls == [
        ("project_session_settings", {}),
        ("set_project_idle_timeout", {"idle_timeout_seconds": 120}),
    ]


def test_reverse_client_uses_long_private_mcp_timeout() -> None:
    client = ReverseAdminClient("http://example.test/mcp")

    assert client.timeout_seconds == 180.0


@pytest.mark.asyncio
async def test_reverse_worker_recovery_controls_use_private_backend_tools() -> None:
    client = FakeReverseAdminClient(
        {
            "clear_worker_queue": {
                "worker_index": 0,
                "cancelled_total": 3,
                "cancelled_queued": 3,
                "cancelled_running": 0,
            },
            "recover_worker": {
                "worker_index": 0,
                "recovered": True,
                "cancelled_total": 4,
                "cancelled_queued": 3,
                "cancelled_running": 1,
            },
        }
    )

    cleared = await client.clear_worker_queue(0)
    recovered = await client.recover_worker(0, timeout_seconds=12)

    assert cleared["cancelled_queued"] == 3
    assert recovered["recovered"] is True
    assert client.calls == [
        ("clear_worker_queue", {"worker_index": 0}),
        ("recover_worker", {"worker_index": 0, "timeout_seconds": 12}),
    ]
