"""SEC EDGAR retrieval and filing-section extraction."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup

from us_gov_research.errors import SourceError
from us_gov_research.evidence import EvidenceRecord
from us_gov_research.http import GovernmentClient

from .common import clean_text, evidence, relevant_excerpt


async def search_sec(
    client: GovernmentClient,
    *,
    user_agent: str,
    query: str,
    company: str | None = None,
    cik: str | None = None,
    form_type: str = "10-K",
    latest: bool = True,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 5,
) -> list[EvidenceRecord]:
    """Search a company's filings, or use EDGAR full-text search when no company is given."""

    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    resolved_cik = _normalize_cik(cik) if cik else None
    if not resolved_cik and company:
        resolved_cik = await _resolve_cik(client, company, headers)
    if resolved_cik:
        return await _company_filings(
            client,
            headers=headers,
            query=query,
            cik=resolved_cik,
            form_type=form_type,
            latest=latest,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    return await _full_text_search(
        client,
        headers=headers,
        query=query,
        form_type=form_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


def _normalize_cik(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    if not digits or len(digits) > 10:
        raise SourceError("sec", "CIK must contain at most 10 digits")
    return digits.zfill(10)


async def _resolve_cik(client: GovernmentClient, company: str, headers: dict[str, str]) -> str:
    payload = await client.get_json(
        "sec",
        "https://www.sec.gov/files/company_tickers.json",
        headers=headers,
        ttl_seconds=86_400,
    )
    needle = company.strip().lower()
    candidates: list[tuple[int, str]] = []
    for row in payload.values():
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker", "")).lower()
        title = str(row.get("title", "")).lower()
        score = 0
        if needle == ticker:
            score = 100
        elif needle == title:
            score = 90
        elif needle in title:
            score = 70
        elif title and all(part in title for part in needle.split()):
            score = 50
        if score:
            candidates.append((score, str(row.get("cik_str", ""))))
    if not candidates:
        raise SourceError("sec", f"could not resolve company {company!r} to a CIK")
    candidates.sort(reverse=True)
    return _normalize_cik(candidates[0][1])


async def _company_filings(
    client: GovernmentClient,
    *,
    headers: dict[str, str],
    query: str,
    cik: str,
    form_type: str,
    latest: bool,
    start_date: str | None,
    end_date: str | None,
    limit: int,
) -> list[EvidenceRecord]:
    payload = await client.get_json(
        "sec",
        f"https://data.sec.gov/submissions/CIK{cik}.json",
        headers=headers,
        ttl_seconds=300,
    )
    recent = payload.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        raise SourceError("sec", "submissions response did not contain recent filings")
    rows = _columnar_rows(recent)
    wanted_form = form_type.upper().strip()
    selected = []
    for row in rows:
        filed = str(row.get("filingDate", ""))
        if wanted_form and str(row.get("form", "")).upper() != wanted_form:
            continue
        if start_date and filed < start_date:
            continue
        if end_date and filed > end_date:
            continue
        selected.append(row)
    selected.sort(key=lambda row: str(row.get("filingDate", "")), reverse=True)
    selected = selected[:1] if latest else selected[: max(1, min(limit, 10))]
    if not selected:
        raise SourceError("sec", f"no {form_type} filings matched the requested dates")

    results: list[EvidenceRecord] = []
    company_name = str(payload.get("name", f"CIK {cik}"))
    for row in selected:
        accession = str(row.get("accessionNumber", ""))
        primary = str(row.get("primaryDocument", ""))
        if not accession or not primary:
            continue
        archive_cik = str(int(cik))
        archive_accession = accession.replace("-", "")
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{archive_cik}/"
            f"{archive_accession}/{quote(primary)}"
        )
        html = await client.get_text(
            "sec",
            url,
            headers={**headers, "Accept": "text/html,application/xhtml+xml"},
            ttl_seconds=31_536_000,
        )
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        excerpt = _filing_excerpt(text, query)
        results.append(
            evidence(
                source="sec",
                title=f"{company_name} {row.get('form')} filed {row.get('filingDate')}",
                canonical_url=url,
                document_id=accession,
                published_at=row.get("filingDate"),
                excerpt=excerpt,
                fields={
                    "cik": cik,
                    "company": company_name,
                    "form": row.get("form"),
                    "filing_date": row.get("filingDate"),
                    "report_date": row.get("reportDate"),
                    "accession_number": accession,
                },
            )
        )
    if not results:
        raise SourceError("sec", "matching filing metadata lacked a retrievable primary document")
    return results


def _columnar_rows(columns: dict[str, Any]) -> list[dict[str, Any]]:
    lengths = [len(value) for value in columns.values() if isinstance(value, list)]
    row_count = max(lengths, default=0)
    return [
        {
            key: value[index] if isinstance(value, list) and index < len(value) else None
            for key, value in columns.items()
        }
        for index in range(row_count)
    ]


def _filing_excerpt(text: str, query: str) -> str:
    lower_query = query.lower()
    if "risk" in lower_query:
        compact = clean_text(text, max_chars=max(len(text), 12_000))
        lower = compact.lower()
        candidates: list[str] = []
        for start_match in re.finditer(r"item\s+1a[.\s:—-]", lower):
            start = start_match.start()
            search_from = start_match.end()
            tail = lower[search_from:]
            end_match = re.search(r"item\s+(?:1b|1c|2)[.\s:—-]", tail)
            end = search_from + end_match.start() if end_match else start + 12_000
            segment = compact[start:end]
            if len(segment) > 100:
                candidates.append(segment)
        if candidates:
            return clean_text(max(candidates, key=len), max_chars=12_000)
    return relevant_excerpt(text, query)


async def _full_text_search(
    client: GovernmentClient,
    *,
    headers: dict[str, str],
    query: str,
    form_type: str,
    start_date: str | None,
    end_date: str | None,
    limit: int,
) -> list[EvidenceRecord]:
    params: dict[str, Any] = {
        "q": query,
        "forms": form_type,
        "from": 0,
        "size": max(1, min(limit, 10)),
    }
    if start_date or end_date:
        params.update(
            {
                "dateRange": "custom",
                "startdt": start_date or "2001-01-01",
                "enddt": end_date or "2099-12-31",
            }
        )
    payload = await client.get_json(
        "sec",
        "https://efts.sec.gov/LATEST/search-index",
        params=params,
        headers=headers,
        ttl_seconds=900,
    )
    hits = payload.get("hits", {}).get("hits", [])
    results: list[EvidenceRecord] = []
    for hit in hits[: max(1, min(limit, 10))]:
        source = hit.get("_source", {}) if isinstance(hit, dict) else {}
        hit_id = str(hit.get("_id", ""))
        accession, _, filename = hit_id.partition(":")
        ciks = source.get("ciks", [])
        cik = str(ciks[0]).lstrip("0") if ciks else ""
        if not accession or not filename or not cik:
            continue
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/"
            f"{accession.replace('-', '')}/{quote(filename)}"
        )
        display_names = source.get("display_names", [])
        title = display_names[0] if display_names else source.get("file_description", hit_id)
        results.append(
            evidence(
                source="sec",
                title=title,
                canonical_url=url,
                document_id=accession,
                published_at=source.get("file_date"),
                excerpt=(
                    f"EDGAR full-text match for {query!r}. Form {source.get('form')}; "
                    f"description {source.get('file_description')}; period ending "
                    f"{source.get('period_ending')}."
                ),
                fields={"form": source.get("form"), "ciks": ciks},
            )
        )
    if not results:
        raise SourceError("sec", "EDGAR full-text search returned no matches")
    return results
