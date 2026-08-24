from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

import us_gov_research.agent as agent_module
from us_gov_research.agent import SYSTEM_PROMPT, TOOLS, AgentDependencies
from us_gov_research.config import Settings
from us_gov_research.evidence import EvidenceRecord


@pytest.mark.asyncio
async def test_acceptance_flow_uses_sec_tool_and_renders_primary_citation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sec(*args: Any, **kwargs: Any) -> list[EvidenceRecord]:
        return [
            EvidenceRecord(
                source="sec",
                title="Tesla, Inc. 10-K filed 2026-02-01",
                canonical_url=(
                    "https://www.sec.gov/Archives/edgar/data/1318605/"
                    "000162828026012345/tsla-20251231.htm"
                ),
                document_id="0001628280-26-012345",
                published_at="2026-02-01",
                excerpt="Supply-chain and competition risks were disclosed.",
            )
        ]

    monkeypatch.setattr(agent_module, "search_sec", fake_sec)
    test_agent: Agent[AgentDependencies, str] = Agent(
        TestModel(
            call_tools=["search_sec_edgar"],
            custom_output_text="Tesla disclosed supply-chain and competition risks. [S1]",
        ),
        deps_type=AgentDependencies,
        instructions=SYSTEM_PROMPT,
        tools=TOOLS,
    )
    monkeypatch.setattr(agent_module, "build_agent", lambda settings: test_agent)
    settings = Settings(
        openai_api_key=SecretStr("placeholder-test-value"),
        sec_user_agent="Test Researcher test@valid.test",
    )

    result = await agent_module.run_research(
        "What were Tesla's most recently disclosed risk factors?",
        settings,
        use_cache=False,
    )

    assert "Tesla disclosed" in result.answer
    assert "[S1](https://www.sec.gov/Archives/edgar/data/" in result.answer
    assert "## Sources" in result.answer
    assert result.http_requests == 0
