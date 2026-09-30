from __future__ import annotations

from typing import Any

import pytest

from management.infrastructure.reverse import ReverseAdminClient


class FakeReverseAdminClient(ReverseAdminClient):
    def __init__(self, responses: dict[str, Any]) -> None:
        super().__init__("http://unused")
        self.responses = responses

    async def _call(self, tool: str, arguments=None):
        del arguments
        return self.responses[tool]


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
    assert projects[1]["worker_index"] is None


@pytest.mark.asyncio
async def test_reverse_open_programs_normalizes_backend_shapes() -> None:
    client = FakeReverseAdminClient(
        {"list_open_programs": {"programs": ["a.bin", {"name": "b.bin", "open": True}]}}
    )

    programs = await client.open_programs("ghp_alpha")

    assert programs == ["a.bin", {"name": "b.bin", "open": True}]
