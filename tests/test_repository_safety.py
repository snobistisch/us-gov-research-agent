from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_env_is_ignored_and_example_is_kept() -> None:
    lines = (ROOT / ".gitignore").read_text().splitlines()

    assert ".env" in lines
    assert ".env.*" in lines
    assert "!.env.example" in lines


def test_example_contains_only_placeholders() -> None:
    example = (ROOT / ".env.example").read_text()

    assert "OPENAI_API_KEY=replace-with" in example
    assert "DATA_GOV_API_KEY=replace-with" in example
    assert "sk-" not in example


def test_exactly_seven_agent_tools_are_exposed() -> None:
    from us_gov_research.agent import TOOLS

    assert [tool.__name__ for tool in TOOLS] == [
        "search_sec_edgar",
        "search_congress",
        "search_federal_register",
        "search_usaspending",
        "query_treasury_fiscal_data",
        "search_regulations_gov",
        "search_govinfo",
    ]


def test_hermes_example_contains_paths_not_credentials() -> None:
    config = (ROOT / "hermes" / "config.example.yaml").read_text()
    skill = (ROOT / ".hermes" / "skills" / "sec-federal-research" / "SKILL.md").read_text()

    assert "${US_GOV_RESEARCH_AGENT_BIN}" in config
    assert "${US_GOV_RESEARCH_AGENT_ENV_FILE}" in config
    assert "${US_GOV_RESEARCH_AGENT_SKILLS_DIR}" in config
    assert "API_KEY" not in config
    assert "supports_parallel_tool_calls: true" in config
    assert "sampling:\n      enabled: false" in config
    assert "allowed-tools:" in skill
    assert "requires_toolsets:" in skill
