from __future__ import annotations

from typing import Any

import pytest

from us_gov_research.errors import SourceError
from us_gov_research.tools.congress import (
    _bill_evidence,
    _filter_rows,
    _member_evidence,
    _parse_bill,
    search_congress_api,
)


class CongressStubClient:
    def __init__(self, pages: dict[int, dict[str, Any]]) -> None:
        self.pages = pages
        self.offsets: list[int] = []
        self.params: list[dict[str, Any]] = []

    async def get_json(self, source: str, url: str, **kwargs: Any) -> dict[str, Any]:
        assert source == "congress"
        offset = int(kwargs["params"]["offset"])
        self.offsets.append(offset)
        self.params.append(kwargs["params"])
        return self.pages[offset]


class MemberDetailStubClient:
    async def get_json(self, source: str, url: str, **kwargs: Any) -> dict[str, Any]:
        assert source == "congress"
        assert url.endswith("/member/W000817")
        assert kwargs["params"] == {"api_key": "fixture-key", "format": "json"}
        return {
            "member": {
                "invertedOrderName": "Warren, Elizabeth",
                "directOrderName": "Elizabeth Warren",
                "firstName": "Elizabeth",
                "lastName": "Warren",
                "bioguideId": "W000817",
                "currentMember": True,
                "partyHistory": [
                    {"partyName": "Democratic", "startYear": 2013},
                ],
                "state": "Massachusetts",
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
        current_member=True,
    )

    assert client.offsets == [0, 250]
    assert all(params["currentMember"] == "true" for params in client.params)
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
    assert records[0].title == "Warren, Elizabeth"
    assert records[0].fields["normalized_party"] == "Democratic"
    assert "party Democratic" in records[0].excerpt
    assert "None" not in records[0].excerpt


@pytest.mark.asyncio
async def test_exact_bioguide_respects_current_member_scope() -> None:
    with pytest.raises(SourceError, match="current-member scope"):
        await search_congress_api(
            MemberDetailStubClient(),  # type: ignore[arg-type]
            api_key="fixture-key",
            query="W000817",
            resource="member",
            current_member=False,
        )


def test_member_normalization_falls_back_to_names_and_latest_party_history() -> None:
    record = _member_evidence(
        {
            "firstName": "Casey",
            "lastName": "Researcher",
            "partyHistory": {
                "item": [
                    {"partyName": "First Party", "startYear": 1990, "endYear": 1994},
                    {"partyName": "Second Party", "startYear": 1995, "endYear": 2000},
                ]
            },
        },
        "R000001",
    )

    assert record.title == "Casey Researcher"
    assert record.fields["normalized_party"] == "Second Party"
    assert "None" not in record.excerpt


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
async def test_current_member_scope_is_rejected_for_non_member_resources() -> None:
    with pytest.raises(SourceError, match="only be used with member"):
        await search_congress_api(
            CongressStubClient({}),  # type: ignore[arg-type]
            api_key="fixture-key",
            query="health care",
            resource="bill",
            current_member=True,
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


def test_filter_rows_uses_word_tokens_instead_of_substrings() -> None:
    rows = [
        {"title": "Presidential determination and termination authority"},
        {"title": "Congressional term limits amendment"},
    ]

    assert _filter_rows(rows, "term", ("title",), 5) == [rows[1]]
    assert _filter_rows([{"title": "New authority"}], "news", ("title",), 5) == []


def test_bill_results_rank_relevance_then_congress_and_action_date() -> None:
    rows = [
        {
            "title": "Health Care Resolution",
            "congress": 110,
            "latestAction": {"actionDate": "2008-01-01"},
        },
        {
            "title": "Health Care Act",
            "congress": 119,
            "latestAction": {"actionDate": "2026-02-01"},
        },
        {
            "title": "Health Act",
            "congress": 119,
            "latestAction": {"actionDate": "2026-08-01"},
        },
    ]

    ranked = _filter_rows(
        rows,
        "health care",
        ("title",),
        3,
        rank_by_recency=True,
    )

    assert ranked == [rows[1], rows[0], rows[2]]


@pytest.mark.parametrize(
    ("query", "bill_type"),
    [
        ("H.R. 42", "hr"),
        ("S. 42", "s"),
        ("H.Res. 42", "hres"),
        ("S.Res. 42", "sres"),
        ("H.J.Res. 42", "hjres"),
        ("S.J.Res. 42", "sjres"),
        ("H.Con.Res. 42", "hconres"),
        ("S.Con.Res. 42", "sconres"),
    ],
)
def test_parse_bill_supports_all_congress_gov_types(query: str, bill_type: str) -> None:
    assert _parse_bill(query, 119) == (119, bill_type, "42")


@pytest.mark.parametrize(
    ("bill_type", "slug"),
    [
        ("hconres", "house-concurrent-resolution"),
        ("sconres", "senate-concurrent-resolution"),
    ],
)
def test_concurrent_resolution_uses_public_congress_url(bill_type: str, slug: str) -> None:
    record = _bill_evidence(
        {"title": "Concurrent resolution"},
        119,
        bill_type,
        "42",
    )

    assert record.canonical_url.endswith(f"/{slug}/42")
