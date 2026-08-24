"""GovInfo search and official-package adapter."""

from __future__ import annotations

from us_gov_research.errors import SourceError
from us_gov_research.evidence import EvidenceRecord
from us_gov_research.http import GovernmentClient

from .common import evidence


async def search_govinfo_api(
    client: GovernmentClient,
    *,
    api_key: str,
    query: str,
    collection: str | None = None,
    limit: int = 5,
) -> list[EvidenceRecord]:
    """Search official GPO packages across all three federal branches."""

    search_query = query if not collection else f"collection:({collection}) AND ({query})"
    body = {
        "query": search_query,
        "pageSize": max(1, min(limit, 10)),
        "offsetMark": "*",
        "sorts": [{"field": "score", "sortOrder": "DESC"}],
    }
    payload = await client.post_json(
        "govinfo",
        "https://api.govinfo.gov/search",
        params={"api_key": api_key},
        json_body=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        ttl_seconds=21_600,
    )
    rows = payload.get("results", payload.get("packages", []))
    results = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        package_id = str(row.get("packageId") or row.get("packageid") or "")
        if not package_id:
            continue
        title = row.get("title") or row.get("packageTitle") or package_id
        url = f"https://www.govinfo.gov/app/details/{package_id}"
        results.append(
            evidence(
                source="govinfo",
                title=title,
                canonical_url=url,
                document_id=package_id,
                published_at=row.get("dateIssued") or row.get("publishDate"),
                excerpt=(
                    f"{row.get('title') or row.get('packageTitle')}. Collection: "
                    f"{row.get('collectionCode') or row.get('collection')}. "
                    f"Date issued: {row.get('dateIssued') or row.get('publishDate')}. "
                    f"Result summary: {row.get('summary') or row.get('description') or ''}"
                ),
                fields=row,
            )
        )
    if not results:
        raise SourceError("govinfo", "no GovInfo packages matched the query")
    return results
