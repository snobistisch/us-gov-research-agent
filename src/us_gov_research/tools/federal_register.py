"""Federal Register API v1 adapter."""

from __future__ import annotations

from typing import Any

from us_gov_research.errors import SourceError
from us_gov_research.evidence import EvidenceRecord
from us_gov_research.http import GovernmentClient

from .common import evidence


async def search_federal_register_api(
    client: GovernmentClient,
    *,
    query: str,
    agency: str | None = None,
    document_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 5,
) -> list[EvidenceRecord]:
    """Search rules, proposed rules, notices, and presidential documents."""

    params: dict[str, Any] = {
        "conditions[term]": query,
        "per_page": max(1, min(limit, 10)),
        "order": "newest",
    }
    if agency:
        params["conditions[agencies][]"] = agency
    if document_type:
        params["conditions[type][]"] = document_type.upper()
    if start_date:
        params["conditions[publication_date][gte]"] = start_date
    if end_date:
        params["conditions[publication_date][lte]"] = end_date
    payload = await client.get_json(
        "federal_register",
        "https://www.federalregister.gov/api/v1/documents.json",
        params=params,
        headers={"Accept": "application/json"},
        ttl_seconds=3600,
    )
    rows = payload.get("results", [])
    results = []
    for row in rows[: max(1, min(limit, 10))] if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        url = row.get("html_url") or row.get("pdf_url")
        if not isinstance(url, str):
            continue
        agencies = row.get("agencies", [])
        agency_names = [
            item.get("name") for item in agencies if isinstance(item, dict) and item.get("name")
        ]
        results.append(
            evidence(
                source="federal_register",
                title=row.get("title", row.get("document_number", "Federal Register document")),
                canonical_url=url,
                document_id=row.get("document_number", ""),
                published_at=row.get("publication_date"),
                excerpt=(
                    f"{row.get('abstract', '')} Type: {row.get('type')}. "
                    f"Agencies: {', '.join(agency_names)}. "
                    f"Effective date: {row.get('effective_on')}."
                ),
                fields={
                    "document_number": row.get("document_number"),
                    "type": row.get("type"),
                    "agencies": agency_names,
                    "cfr_references": row.get("cfr_references", []),
                    "docket_ids": row.get("docket_ids", []),
                    "comments_close_on": row.get("comments_close_on"),
                    "official_pdf_url": row.get("pdf_url"),
                },
            )
        )
    if not results:
        raise SourceError("federal_register", "no Federal Register documents matched the query")
    return results
