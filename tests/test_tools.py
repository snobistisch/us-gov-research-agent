from __future__ import annotations

from typing import Any

import pytest

from us_gov_research.tools.federal_register import search_federal_register_api
from us_gov_research.tools.govinfo import search_govinfo_api
from us_gov_research.tools.regulations import search_regulations_api
from us_gov_research.tools.treasury import query_treasury_api
from us_gov_research.tools.usaspending import search_usaspending_api


class StubClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.last_url = ""

    async def get_json(self, source: str, url: str, **kwargs: Any) -> dict[str, Any]:
        self.last_url = url
        return self.payload

    async def post_json(self, source: str, url: str, **kwargs: Any) -> dict[str, Any]:
        self.last_url = url
        return self.payload


@pytest.mark.asyncio
async def test_federal_register_normalization() -> None:
    client = StubClient(
        {
            "results": [
                {
                    "title": "A final rule",
                    "document_number": "2026-12345",
                    "publication_date": "2026-08-01",
                    "abstract": "The agency adopts a rule.",
                    "type": "Rule",
                    "html_url": "https://www.federalregister.gov/documents/2026/08/01/example",
                    "pdf_url": "https://www.govinfo.gov/content/pkg/example.pdf",
                    "agencies": [{"name": "Example Agency"}],
                }
            ]
        }
    )

    records = await search_federal_register_api(client, query="example")  # type: ignore[arg-type]

    assert records[0].document_id == "2026-12345"
    assert records[0].fields["agencies"] == ["Example Agency"]


@pytest.mark.asyncio
async def test_usaspending_normalization() -> None:
    client = StubClient(
        {
            "results": [
                {
                    "Award ID": "ABC123",
                    "generated_internal_id": "CONT_AWD_ABC123",
                    "Recipient Name": "Example Corp",
                    "Award Amount": 42,
                    "Awarding Agency": "Example Agency",
                    "Award Description": "Research",
                    "Start Date": "2026-01-01",
                    "End Date": "2026-12-31",
                }
            ]
        }
    )

    records = await search_usaspending_api(client, query="research")  # type: ignore[arg-type]

    assert records[0].canonical_url.endswith("CONT_AWD_ABC123")
    assert "Example Corp" in records[0].excerpt


@pytest.mark.asyncio
async def test_treasury_normalization() -> None:
    client = StubClient(
        {"data": [{"record_date": "2026-08-01", "tot_pub_debt_out_amt": "42000000000000"}]}
    )

    records = await query_treasury_api(client, dataset="debt_to_penny")  # type: ignore[arg-type]

    assert records[0].published_at == "2026-08-01"
    assert "42000000000000" in records[0].excerpt


@pytest.mark.asyncio
async def test_regulations_normalization() -> None:
    client = StubClient(
        {
            "data": [
                {
                    "id": "EPA-2026-0001-0001",
                    "attributes": {
                        "title": "Proposed rule",
                        "agencyId": "EPA",
                        "docketId": "EPA-2026-0001",
                        "postedDate": "2026-08-01",
                        "documentType": "Proposed Rule",
                    },
                }
            ]
        }
    )

    records = await search_regulations_api(
        client,
        api_key="not-a-real-key",
        query="emissions",  # type: ignore[arg-type]
    )

    assert records[0].canonical_url.endswith("EPA-2026-0001-0001")


@pytest.mark.asyncio
async def test_govinfo_normalization() -> None:
    client = StubClient(
        {
            "results": [
                {
                    "packageId": "BILLS-119hr1enr",
                    "title": "H.R. 1",
                    "collectionCode": "BILLS",
                    "dateIssued": "2026-08-01",
                }
            ]
        }
    )

    records = await search_govinfo_api(
        client,
        api_key="not-a-real-key",
        query="H.R. 1",  # type: ignore[arg-type]
    )

    assert records[0].canonical_url == "https://www.govinfo.gov/app/details/BILLS-119hr1enr"
