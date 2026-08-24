from __future__ import annotations

from typing import Any

import pytest

from us_gov_research.errors import SourceError
from us_gov_research.tools.congress import _filter_rows, search_congress_api


class CongressStubClient:
    def __init__(self, pages: dict[int, dict[str, Any]]) -> None:
        self.pages = pages
        self.offsets: list[int] = []

    async def get_json(self, source: str, url: str, **kwargs: Any) -> dict[str, Any]:
        assert source == "congress"
        offset = int(kwargs["params"]["offset"])
        self.offsets.append(offset)
        return self.pages[offset]


class MemberDetailStubClient:
    async def get_json(self, source: str, url: str, **kwargs: Any) -> dict[str, Any]:
        assert source == "congress"
        assert url.endswith("/member/W000817")
        assert kwargs["params"] == {"api_key": "fixture-key", "format": "json"}
        return {
            "member": {
                "name": "Warren, Elizabeth",
                "bioguideId": "W000817",
                "partyName": "Democratic",
                "state": "MA",
            }
        }


def _members(start: int, count: int) -> list[dict[str, Any]]:
    return [
        {
            "name": f"Member {number}",
            "bioguideId": f"X{number:06d}",
            "partyName": "Independent",
            "state": "ZZ",
        }
        for number in range(start, start + count)
    ]


@pytest.mark.asyncio
async def test_member_search_paginates_to_find_warren() -> None:
    client = CongressStubClient(
        {
            0: {
                "members": _members(0, 250),
                "pagination": {"count": 251, "next": "next-page"},
            },
            250: {
                "members": [
                    {
                        "name": "Warren, Elizabeth",
                        "bioguideId": "W000817",
                        "partyName": "Democratic",
                        "state": "MA",
                    }
                ],
                "pagination": {"count": 251},
            },
        }
    )

    records = await search_congress_api(
        client,  # type: ignore[arg-type]
        api_key="fixture-key",
        query="Elizabeth Warren",
        resource="member",
    )

    assert client.offsets == [0, 250]
    assert records[0].document_id == "W000817"
    assert "coverage_note" not in records[0].fields


@pytest.mark.asyncio
async def test_exact_bioguide_id_uses_member_detail_endpoint() -> None:
    records = await search_congress_api(
        MemberDetailStubClient(),  # type: ignore[arg-type]
        api_key="fixture-key",
        query="W000817",
        resource="member",
    )

    assert records[0].document_id == "W000817"


@pytest.mark.asyncio
async def test_house_vote_search_paginates_beyond_first_page() -> None:
    first_page = [
        {"rollCallNumber": number, "question": "On agreeing to the motion"}
        for number in range(1, 251)
    ]
    client = CongressStubClient(
        {
            0: {
                "houseRollCallVotes": first_page,
                "pagination": {"count": 251, "next": "next-page"},
            },
            250: {
                "houseRollCallVotes": [
                    {
                        "rollCallNumber": 251,
                        "question": "Artificial intelligence transparency",
                        "result": "Passed",
                        "legislationNumber": "H.R. 42",
                    }
                ],
                "pagination": {"count": 251},
            },
        }
    )

    records = await search_congress_api(
        client,  # type: ignore[arg-type]
        api_key="fixture-key",
        query="artificial intelligence",
        resource="house_vote",
        congress=119,
        session=1,
    )

    assert client.offsets == [0, 250]
    assert records[0].document_id == "119-1-251"


@pytest.mark.asyncio
async def test_bill_no_match_raises_consistent_source_error() -> None:
    client = CongressStubClient(
        {
            0: {
                "bills": [{"congress": 119, "type": "HR", "number": "1", "title": "Tax"}],
                "pagination": {"count": 1},
            }
        }
    )

    with pytest.raises(SourceError, match="no bill records matched"):
        await search_congress_api(
            client,  # type: ignore[arg-type]
            api_key="fixture-key",
            query="quantum fisheries",
            resource="bill",
        )


@pytest.mark.asyncio
async def test_bounded_bill_scan_discloses_coverage_limit() -> None:
    pages: dict[int, dict[str, Any]] = {}
    for offset in (0, 250, 500, 750):
        bills = [
            {
                "congress": 119,
                "type": "HR",
                "number": str(offset + number + 1),
                "title": f"Routine bill {offset + number + 1}",
            }
            for number in range(250)
        ]
        if offset == 750:
            bills[-1]["title"] = "Rareterm research act"
        pages[offset] = {
            "bills": bills,
            "pagination": {"count": 1_250, "next": "next-page"},
        }
    client = CongressStubClient(pages)

    records = await search_congress_api(
        client,  # type: ignore[arg-type]
        api_key="fixture-key",
        query="rareterm",
        resource="bill",
    )

    assert client.offsets == [0, 250, 500, 750]
    assert "limited to 1000 list records" in records[0].fields["coverage_note"]


def test_filter_rows_rejects_query_without_search_terms() -> None:
    assert _filter_rows([{"title": "Arbitrary first row"}], "!!!", ("title",), 5) == []
