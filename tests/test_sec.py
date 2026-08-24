from __future__ import annotations

from typing import Any

import pytest

from us_gov_research.tools.sec import search_sec


class SecStubClient:
    async def get_json(self, source: str, url: str, **kwargs: Any) -> dict[str, Any]:
        assert source == "sec"
        if url.endswith("company_tickers.json"):
            return {"0": {"cik_str": 1318605, "ticker": "TSLA", "title": "Tesla, Inc."}}
        if "submissions" in url:
            return {
                "name": "Tesla, Inc.",
                "filings": {
                    "recent": {
                        "accessionNumber": ["0001628280-26-012345", "0001628280-25-012344"],
                        "filingDate": ["2026-02-01", "2025-02-01"],
                        "reportDate": ["2025-12-31", "2024-12-31"],
                        "form": ["10-K", "10-K"],
                        "primaryDocument": ["tsla-20251231.htm", "tsla-20241231.htm"],
                    }
                },
            }
        raise AssertionError(f"Unexpected URL: {url}")

    async def get_text(self, source: str, url: str, **kwargs: Any) -> str:
        assert source == "sec"
        assert "000162828026012345" in url
        return """
        <html><body>
        <h2>Item 1A. Risk Factors</h2>
        <p>Supply chain interruptions could delay production and increase costs.</p>
        <p>Competition may reduce demand for our products.</p>
        <h2>Item 1B. Unresolved Staff Comments</h2>
        <p>None.</p>
        </body></html>
        """


@pytest.mark.asyncio
async def test_latest_tesla_risk_factors_use_primary_filing() -> None:
    records = await search_sec(
        SecStubClient(),  # type: ignore[arg-type]
        user_agent="Test Researcher test@valid.test",
        query="most recently disclosed risk factors",
        company="Tesla",
        form_type="10-K",
        latest=True,
    )

    assert len(records) == 1
    assert records[0].document_id == "0001628280-26-012345"
    assert records[0].canonical_url.startswith("https://www.sec.gov/Archives/edgar/data/")
    assert "Supply chain interruptions" in records[0].excerpt
    assert "Unresolved Staff Comments" not in records[0].excerpt
