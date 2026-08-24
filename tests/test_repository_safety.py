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
