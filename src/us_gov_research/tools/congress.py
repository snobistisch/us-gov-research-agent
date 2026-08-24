"""Congress.gov API v3 adapter."""

from __future__ import annotations

import re
from typing import Literal

from us_gov_research.errors import SourceError
from us_gov_research.evidence import EvidenceRecord
from us_gov_research.http import GovernmentClient

from .common import evidence

CongressResource = Literal["bill", "member", "house_vote"]


async def search_congress_api(
    client: GovernmentClient,
    *,
    api_key: str,
    query: str,
    resource: CongressResource = "bill",
    congress: int | None = None,
    session: int | None = None,
    limit: int = 5,
) -> list[EvidenceRecord]:
    """Find bills, members, or House roll-call votes in Congress.gov API v3."""

    params = {"api_key": api_key, "format": "json", "limit": 250}
    if resource == "bill":
        detail = _parse_bill(query, congress)
        if detail:
            bill_congress, bill_type, number = detail
            payload = await client.get_json(
                "congress",
                f"https://api.congress.gov/v3/bill/{bill_congress}/{bill_type}/{number}",
                params=params,
                ttl_seconds=21_600,
            )
            bill = payload.get("bill", payload)
            return [_bill_evidence(bill, bill_congress, bill_type, number)]
        url = "https://api.congress.gov/v3/bill"
        if congress:
            url += f"/{congress}"
        payload = await client.get_json("congress", url, params=params, ttl_seconds=21_600)
        rows = payload.get("bills", [])
        filtered = _filter_rows(rows, query, ("title", "number", "type"), limit)
        return [
            _bill_evidence(
                row,
                int(row.get("congress", congress or 0)),
                str(row.get("type", "")).lower(),
                str(row.get("number", "")),
            )
            for row in filtered
        ]

    if resource == "member":
        payload = await client.get_json(
            "congress",
            "https://api.congress.gov/v3/member",
            params=params,
            ttl_seconds=21_600,
        )
        rows = _filter_rows(
            payload.get("members", []), query, ("name", "state", "partyName"), limit
        )
        results = []
        for row in rows:
            bioguide = str(row.get("bioguideId", ""))
            results.append(
                evidence(
                    source="congress",
                    title=row.get("name", bioguide),
                    canonical_url=f"https://www.congress.gov/member/{bioguide}",
                    document_id=bioguide,
                    published_at=row.get("updateDate"),
                    excerpt=(
                        f"Congress member {row.get('name')}; party {row.get('partyName')}; "
                        f"state {row.get('state')}; district {row.get('district')}."
                    ),
                    fields=row,
                )
            )
        return _require_results(results, resource)

    if congress is None or session is None:
        raise SourceError("congress", "house_vote requires congress and session")
    payload = await client.get_json(
        "congress",
        f"https://api.congress.gov/v3/house-vote/{congress}/{session}",
        params=params,
        ttl_seconds=86_400,
    )
    rows = payload.get("houseRollCallVotes", payload.get("houseVotes", []))
    filtered = _filter_rows(rows, query, ("question", "description", "legislationNumber"), limit)
    results = []
    for row in filtered:
        vote_number = str(row.get("rollCallNumber", row.get("voteNumber", "")))
        results.append(
            evidence(
                source="congress",
                title=f"House roll call {vote_number}: {row.get('question', 'vote')}",
                canonical_url=(
                    f"https://www.congress.gov/roll-call-vote/{congress}th-congress/"
                    f"{session}{_ordinal_suffix(session)}-session/{vote_number}"
                ),
                document_id=f"{congress}-{session}-{vote_number}",
                published_at=row.get("date"),
                excerpt=(
                    f"Question: {row.get('question')}. Result: {row.get('result')}. "
                    f"Legislation: {row.get('legislationNumber')}."
                ),
                fields=row,
            )
        )
    return _require_results(results, resource)


def _parse_bill(query: str, congress: int | None) -> tuple[int, str, str] | None:
    match = re.search(
        r"\b(h\.?\s*r\.?|s\.?|h\.?\s*res\.?|s\.?\s*res\.?)\s*(\d+)\b",
        query,
        re.IGNORECASE,
    )
    if not match or congress is None:
        return None
    normalized = re.sub(r"[^a-z]", "", match.group(1).lower())
    mapping = {"hr": "hr", "s": "s", "hres": "hres", "sres": "sres"}
    return congress, mapping[normalized], match.group(2)


def _ordinal_suffix(value: int) -> str:
    if 10 <= value % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")


def _filter_rows(
    rows: object, query: str, fields: tuple[str, ...], limit: int
) -> list[dict[str, object]]:
    if not isinstance(rows, list):
        return []
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9-]{2,}", query)]
    scored: list[tuple[int, dict[str, object]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        haystack = " ".join(str(row.get(field, "")) for field in fields).lower()
        score = sum(term in haystack for term in terms)
        if score or not terms:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[: max(1, min(limit, 10))]]


def _bill_evidence(
    bill: dict[str, object], congress: int, bill_type: str, number: str
) -> EvidenceRecord:
    type_slugs = {
        "hr": "house-bill",
        "s": "senate-bill",
        "hres": "house-resolution",
        "sres": "senate-resolution",
        "hjres": "house-joint-resolution",
        "sjres": "senate-joint-resolution",
    }
    slug = type_slugs.get(bill_type, bill_type)
    latest_action = bill.get("latestAction", {})
    if not isinstance(latest_action, dict):
        latest_action = {}
    return evidence(
        source="congress",
        title=bill.get("title", f"{bill_type.upper()} {number}"),
        canonical_url=f"https://www.congress.gov/bill/{congress}th-congress/{slug}/{number}",
        document_id=f"{congress}-{bill_type}-{number}",
        published_at=bill.get("updateDate"),
        excerpt=(
            f"{bill.get('title')}. Introduced {bill.get('introducedDate')}. "
            f"Latest action {latest_action.get('actionDate')}: {latest_action.get('text')}."
        ),
        fields=bill,
    )


def _require_results(results: list[EvidenceRecord], resource: str) -> list[EvidenceRecord]:
    if not results:
        raise SourceError("congress", f"no {resource} records matched the query")
    return results
