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


def test_ai_installers_must_gate_on_user_credentials() -> None:
    readme = (ROOT / "README.md").read_text()
    contract = (ROOT / "AGENT_INSTALL.md").read_text()
    skill = (ROOT / ".hermes" / "skills" / "sec-federal-research" / "SKILL.md").read_text()

    assert readme.index("AGENT_INSTALL.md") < readme.index("## Data sources")
    assert "Stop before running any install" in contract
    assert "Do not run a command until they confirm credential readiness" in contract
    assert "Do not continue until the user replies `configured`" in contract
    assert "Hermes MCP mode uses Hermes' existing model provider" in contract
    assert "| `OPENAI_API_KEY` | Not used |" in contract
    assert "Never read, echo, print" in contract
    assert "Hermes Installation and Evaluation Report" in contract
    assert "read `AGENT_INSTALL.md`" in skill
