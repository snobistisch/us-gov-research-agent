"""USAspending.gov read-only advanced-search adapter."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal
from urllib.parse import quote

from us_gov_research.errors import SourceError
from us_gov_research.evidence import EvidenceRecord
from us_gov_research.http import GovernmentClient

from .common import evidence

AwardGroup = Literal[
    "contracts",
    "grants",
    "loans",
    "direct_payments",
    "other_financial_assistance",
    "idvs",
]

AWARD_TYPES: dict[str, list[str]] = {
    "contracts": ["A", "B", "C", "D"],
    "grants": ["02", "03", "04", "05", "F001", "F002"],
    "loans": ["07", "08", "F003", "F004"],
    "direct_payments": ["09", "F005", "11", "-1", "F008", "F009", "F010"],
    "other_financial_assistance": ["06", "10", "F006", "F007"],
    "idvs": ["IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B", "IDV_B_C", "IDV_C", "IDV_D", "IDV_E"],
}


async def search_usaspending_api(
    client: GovernmentClient,
    *,
    query: str,
    start_date: str | None = None,
    end_date: str | None = None,
    recipient: str | None = None,
    agency: str | None = None,
    award_group: AwardGroup = "contracts",
    limit: int = 5,
) -> list[EvidenceRecord]:
    """Search federal awards, contracts, grants, loans, and direct payments."""

    today = date.today()
    filters: dict[str, object] = {
        "time_period": [
            {
                "start_date": start_date or (today - timedelta(days=5 * 365)).isoformat(),
                "end_date": end_date or today.isoformat(),
            }
        ],
        "award_type_codes": AWARD_TYPES[award_group],
        "keywords": [query],
    }
    if recipient:
        filters["recipient_search_text"] = [recipient]
    if agency:
        filters["agencies"] = [{"type": "awarding", "tier": "toptier", "name": agency}]
    body = {
        "filters": filters,
        "fields": [
            "Award ID",
            "Recipient Name",
            "Award Amount",
            "Awarding Agency",
            "Award Description",
            "Start Date",
            "End Date",
            "generated_internal_id",
        ],
        "page": 1,
        "limit": max(1, min(limit, 10)),
        "subawards": False,
    }
    payload = await client.post_json(
        "usaspending",
        "https://api.usaspending.gov/api/v2/search/spending_by_award/",
        json_body=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        ttl_seconds=21_600,
    )
    rows = payload.get("results", [])
    results = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        internal_id = str(
            row.get("generated_internal_id")
            or row.get("generated_unique_award_id")
            or row.get("Award ID")
            or ""
        )
        if not internal_id:
            continue
        url = f"https://www.usaspending.gov/award/{quote(internal_id, safe='')}"
        results.append(
            evidence(
                source="usaspending",
                title=(
                    f"{row.get('Award ID', internal_id)} — "
                    f"{row.get('Recipient Name', 'recipient unavailable')}"
                ),
                canonical_url=url,
                document_id=internal_id,
                published_at=row.get("Start Date"),
                excerpt=(
                    f"Recipient: {row.get('Recipient Name')}. Awarding agency: "
                    f"{row.get('Awarding Agency')}. Amount: {row.get('Award Amount')}. "
                    f"Description: {row.get('Award Description')}. Period: "
                    f"{row.get('Start Date')} to {row.get('End Date')}."
                ),
                fields=row,
            )
        )
    if not results:
        raise SourceError("usaspending", "no federal awards matched the query")
    return results
