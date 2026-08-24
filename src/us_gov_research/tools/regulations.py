"""Regulations.gov v4 read-only adapter."""

from __future__ import annotations

from typing import Literal

from us_gov_research.errors import SourceError
from us_gov_research.evidence import EvidenceRecord
from us_gov_research.http import GovernmentClient

from .common import evidence

RegulationsResource = Literal["documents", "comments", "dockets"]


async def search_regulations_api(
    client: GovernmentClient,
    *,
    api_key: str,
    query: str,
    resource: RegulationsResource = "documents",
    agency_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 5,
) -> list[EvidenceRecord]:
    """Search regulatory documents, public comments, or dockets without mutation."""

    params: dict[str, object] = {
        "filter[searchTerm]": query,
        "page[size]": max(1, min(limit, 10)),
    }
    if resource != "dockets":
        params["sort"] = "-postedDate"
    if agency_id:
        params["filter[agencyId]"] = agency_id
    if start_date and resource != "dockets":
        params["filter[postedDate][ge]"] = start_date
    if end_date and resource != "dockets":
        params["filter[postedDate][le]"] = end_date
    payload = await client.get_json(
        "regulations",
        f"https://api.regulations.gov/v4/{resource}",
        params=params,
        headers={"Accept": "application/vnd.api+json", "X-Api-Key": api_key},
        ttl_seconds=3600 if resource == "comments" else 21_600,
    )
    rows = payload.get("data", [])
    results = []
    singular = {"documents": "document", "comments": "comment", "dockets": "docket"}[resource]
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        record_id = str(row.get("id", ""))
        attrs = row.get("attributes", {})
        if not record_id or not isinstance(attrs, dict):
            continue
        url = f"https://www.regulations.gov/{singular}/{record_id}"
        title = attrs.get("title") or attrs.get("documentId") or record_id
        excerpt_value = (
            attrs.get("comment")
            or attrs.get("docAbstract")
            or attrs.get("title")
            or f"Regulations.gov {singular} {record_id}"
        )
        results.append(
            evidence(
                source="regulations",
                title=title,
                canonical_url=url,
                document_id=record_id,
                published_at=attrs.get("postedDate") or attrs.get("lastModifiedDate"),
                excerpt=(
                    f"{excerpt_value}. Agency: {attrs.get('agencyId')}. "
                    f"Docket: {attrs.get('docketId')}. Type: "
                    f"{attrs.get('documentType') or attrs.get('docketType')}."
                ),
                fields=attrs,
            )
        )
    if not results:
        raise SourceError("regulations", f"no Regulations.gov {resource} matched the query")
    return results
