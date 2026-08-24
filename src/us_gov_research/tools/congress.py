"""Congress.gov API v3 adapter."""

from __future__ import annotations

import re
from typing import Literal

from us_gov_research.errors import SourceError
from us_gov_research.evidence import EvidenceRecord
from us_gov_research.http import GovernmentClient

from .common import evidence

CongressResource = Literal["bill", "member", "house_vote"]
PAGE_SIZE = 250
MAX_MEMBER_PAGES = 12
MAX_BILL_PAGES = 4
MAX_HOUSE_VOTE_PAGES = 12


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

    params = {"api_key": api_key, "format": "json", "limit": PAGE_SIZE}
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
        rows, complete = await _paged_rows(
            client,
            url=url,
            params=params,
            collection="bills",
            max_pages=MAX_BILL_PAGES,
            ttl_seconds=21_600,
        )
        filtered = _filter_rows(rows, query, ("title", "number", "type"), limit)
        results = [
            _bill_evidence(
                row,
                int(row.get("congress", congress or 0)),
                str(row.get("type", "")).lower(),
                str(row.get("number", "")),
            )
            for row in filtered
        ]
        results = _add_coverage_note(results, complete=complete, scanned=len(rows), resource="bill")
        return _require_results(results, resource, complete=complete, scanned=len(rows))

    if resource == "member":
        bioguide_match = re.search(r"\b[A-Za-z]\d{6}\b", query)
        if bioguide_match:
            bioguide = bioguide_match.group(0).upper()
            payload = await client.get_json(
                "congress",
                f"https://api.congress.gov/v3/member/{bioguide}",
                params={"api_key": api_key, "format": "json"},
                ttl_seconds=21_600,
            )
            member = payload.get("member", payload)
            if not isinstance(member, dict):
                raise SourceError("congress", "member detail returned an unexpected shape")
            return [_member_evidence(member, bioguide)]

        all_rows, complete = await _paged_rows(
            client,
            url="https://api.congress.gov/v3/member",
            params=params,
            collection="members",
            max_pages=MAX_MEMBER_PAGES,
            ttl_seconds=21_600,
        )
        rows = _filter_rows(
            all_rows,
            query,
            ("name", "state", "partyName", "bioguideId"),
            limit,
        )
        results = []
        for row in rows:
            bioguide = str(row.get("bioguideId", ""))
            results.append(_member_evidence(row, bioguide))
        results = _add_coverage_note(
            results,
            complete=complete,
            scanned=len(all_rows),
            resource="member",
        )
        return _require_results(
            results,
            resource,
            complete=complete,
            scanned=len(all_rows),
        )

    if congress is None or session is None:
        raise SourceError("congress", "house_vote requires congress and session")
    all_rows, complete = await _paged_rows(
        client,
        url=f"https://api.congress.gov/v3/house-vote/{congress}/{session}",
        params=params,
        collection="houseRollCallVotes",
        alternate_collection="houseVotes",
        max_pages=MAX_HOUSE_VOTE_PAGES,
        ttl_seconds=86_400,
    )
    filtered = _filter_rows(
        all_rows,
        query,
        ("question", "description", "legislationNumber", "rollCallNumber"),
        limit,
    )
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
    results = _add_coverage_note(
        results, complete=complete, scanned=len(all_rows), resource="house_vote"
    )
    return _require_results(results, resource, complete=complete, scanned=len(all_rows))


async def _paged_rows(
    client: GovernmentClient,
    *,
    url: str,
    params: dict[str, object],
    collection: str,
    max_pages: int,
    ttl_seconds: int,
    alternate_collection: str | None = None,
) -> tuple[list[dict[str, object]], bool]:
    """Collect bounded list pages without following credential-bearing pagination URLs."""

    rows: list[dict[str, object]] = []
    for page in range(max_pages):
        page_params = {**params, "offset": page * PAGE_SIZE}
        payload = await client.get_json(
            "congress",
            url,
            params=page_params,
            ttl_seconds=ttl_seconds,
        )
        raw_rows = payload.get(collection)
        if raw_rows is None and alternate_collection:
            raw_rows = payload.get(alternate_collection)
        batch = (
            [row for row in raw_rows if isinstance(row, dict)]
            if isinstance(raw_rows, list)
            else []
        )
        rows.extend(batch)

        pagination = payload.get("pagination")
        if not isinstance(pagination, dict):
            return rows, len(batch) < PAGE_SIZE
        count = pagination.get("count")
        if isinstance(count, int) and len(rows) >= count:
            return rows, True
        if not pagination.get("next"):
            return rows, True
        if not batch:
            return rows, True
    return rows, False


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
    if not terms:
        return []
    scored: list[tuple[int, dict[str, object]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        haystack = " ".join(str(row.get(field, "")) for field in fields).lower()
        score = sum(term in haystack for term in terms)
        if score:
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


def _member_evidence(member: dict[str, object], bioguide: str) -> EvidenceRecord:
    return evidence(
        source="congress",
        title=member.get("name", bioguide),
        canonical_url=f"https://www.congress.gov/member/{bioguide}",
        document_id=bioguide,
        published_at=member.get("updateDate"),
        excerpt=(
            f"Congress member {member.get('name')}; party {member.get('partyName')}; "
            f"state {member.get('state')}; district {member.get('district')}."
        ),
        fields=member,
    )


def _add_coverage_note(
    results: list[EvidenceRecord], *, complete: bool, scanned: int, resource: str
) -> list[EvidenceRecord]:
    if complete:
        return results
    note = (
        f"Coverage note: free-text {resource} matching was limited to {scanned} list records; "
        "prefer an exact identifier for exhaustive retrieval."
    )
    return [
        record.model_copy(
            update={
                "excerpt": f"{record.excerpt} {note}",
                "fields": {**record.fields, "coverage_note": note},
            }
        )
        for record in results
    ]


def _require_results(
    results: list[EvidenceRecord],
    resource: str,
    *,
    complete: bool = True,
    scanned: int = 0,
) -> list[EvidenceRecord]:
    if not results:
        if not complete:
            raise SourceError(
                "congress",
                f"no {resource} records matched within {scanned} list records; search coverage "
                "was bounded, so use an exact identifier or narrower structural filters",
            )
        raise SourceError("congress", f"no {resource} records matched the query")
    return results
