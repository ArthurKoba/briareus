from __future__ import annotations

from common.mcp_surfaces import MCP_SURFACE_PATHS, resource_url


def test_public_oauth_contract_uses_one_issuer_and_exact_resources() -> None:
    base = "https://mcp.koba-nexus.ru"

    resources = {
        surface: resource_url(base, surface)
        for surface in MCP_SURFACE_PATHS
    }

    assert resources["root"] == "https://mcp.koba-nexus.ru/mcp"
    assert resources["analysis"] == "https://mcp.koba-nexus.ru/analysis/mcp"
    assert "/ghidra/mcp" not in resources.values()
