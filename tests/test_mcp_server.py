from __future__ import annotations

from typing import Any

import pytest
from mcp import Client

import us_gov_research.mcp_server as mcp_server

EXPECTED_TOOLS = {
    "congress_search",
    "federal_register_search",
    "govinfo_search",
    "regulations_search",
    "sec_filings",
    "treasury_fiscal_data",
    "usaspending_search",
}


@pytest.mark.asyncio
async def test_mcp_exposes_exactly_seven_bounded_tools() -> None:
    async with Client(mcp_server.mcp) as client:
        result = await client.list_tools()

    assert {tool.name for tool in result.tools} == EXPECTED_TOOLS
    for tool in result.tools:
        limit = tool.input_schema["properties"]["limit"]
        assert limit["minimum"] == 1
        assert limit["maximum"] == 10
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


@pytest.mark.asyncio
async def test_mcp_call_returns_structured_primary_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call_adapter(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "source": "federal_register",
                "title": "Primary rule",
                "canonical_url": (
                    "https://www.federalregister.gov/documents/2026/08/01/example"
                ),
                "document_id": "2026-12345",
                "published_at": "2026-08-01",
                "excerpt": "The agency published a final rule.",
                "fields": {},
            }
        ]

    monkeypatch.setattr(mcp_server, "_call_adapter", fake_call_adapter)

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool("federal_register_search", {"query": "final rule"})

    assert not result.is_error
    assert result.structured_content is not None
    record = result.structured_content["result"][0]
    assert record["document_id"] == "2026-12345"
    assert record["canonical_url"].startswith("https://www.federalregister.gov/")


@pytest.mark.asyncio
async def test_key_requirement_is_scoped_to_affected_mcp_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATA_GOV_API_KEY", raising=False)

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool("congress_search", {"query": "artificial intelligence"})

    assert result.is_error
    assert "DATA_GOV_API_KEY is required for Congress.gov" in result.content[0].text  # type: ignore[union-attr]
    assert "OPENAI_API_KEY" not in result.content[0].text  # type: ignore[union-attr]
