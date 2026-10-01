from __future__ import annotations

import pytest
from fastmcp import Client

from modules.analysis.runtime import mcp as analysis
from modules.curl.runtime import mcp as curl
from modules.files.runtime import mcp as files
from modules.github.runtime import mcp as github
from modules.gitlab.runtime import mcp as gitlab


async def _tool_names(mcp) -> set[str]:
    async with Client(mcp) as client:
        tools = await client.list_tools()
    return {tool.name for tool in tools}


@pytest.mark.asyncio
async def test_github_runtime_surface_is_isolated() -> None:
    names = await _tool_names(github)

    assert "github_accounts" in names
    assert "github_account_capabilities" in names
    assert "github_agent_status" in names
    assert "github_agent_create_pull_request" in names
    assert "github_agent_workflow_runs" in names
    assert "file_status" not in names
    assert "curl_request" not in names
    assert "accounts" not in names


@pytest.mark.asyncio
async def test_gitlab_runtime_surface_is_isolated() -> None:
    names = await _tool_names(gitlab)

    assert "accounts" in names
    assert "account_status" in names
    assert "account_capabilities" in names
    assert "create_merge_request" in names
    assert "github_agent_status" not in names
    assert "file_status" not in names
    assert "curl_request" not in names


@pytest.mark.asyncio
async def test_files_runtime_surface_is_isolated() -> None:
    names = await _tool_names(files)

    assert {
        "file_status",
        "file_list",
        "file_info",
        "file_read",
        "file_hash",
        "file_write_text",
        "file_write",
        "file_ingest",
        "file_mkdir",
        "file_copy",
        "file_move",
        "file_delete",
    }.issubset(names)
    assert "file_extract" not in names
    assert "file_upload_begin" not in names
    assert "file_collection_list" not in names
    assert "file_workspace_snapshot" not in names
    assert "curl_request" not in names
    assert "github_agent_status" not in names
    assert "accounts" not in names


@pytest.mark.asyncio
async def test_http_runtime_surface_is_isolated() -> None:
    names = await _tool_names(curl)

    assert "curl_presets" in names
    assert "curl_request" in names
    assert "browser_status" in names
    assert "browser_open" in names
    assert "browser_snapshot" in names
    assert "browser_click" in names
    assert "browser_fill" in names
    assert "browser_download" in names
    assert "browser_screenshot" in names
    assert "curl_download" in names
    assert "curl_stream_capture" in names
    assert "file_status" not in names
    assert "github_agent_status" not in names
    assert "accounts" not in names


@pytest.mark.asyncio
async def test_analysis_runtime_surface_is_dynamic_and_isolated() -> None:
    names = await _tool_names(analysis)

    assert "ghidra_import_file" not in names
    assert "ghidra_project_sources" not in names
    assert "ghidra_export_program_file" not in names
    assert "file_status" not in names
    assert "curl_request" not in names
    assert "github_agent_status" not in names
    assert "accounts" not in names


@pytest.mark.asyncio
async def test_terminal_runtime_surface_is_isolated(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TERMINAL_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("TERMINAL_HOME", str(tmp_path / "home"))

    from modules.terminal.runtime import mcp as terminal

    names = await _tool_names(terminal)

    assert "terminal_status" in names
    assert "workspace_create" in names
    assert "terminal_exec" in names
    assert "job_start" in names
    assert "job_read" in names
    assert "job_write" in names
    assert "job_delete" in names
    assert "job_cleanup" in names
    assert "workspace_import_file" not in names
    assert "workspace_export_file" not in names
    assert "github_agent_status" not in names
    assert "curl_request" not in names
    assert "accounts" not in names
