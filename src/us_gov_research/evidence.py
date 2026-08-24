"""Normalized evidence and deterministic citation validation."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .errors import CitationValidationError

OFFICIAL_HOSTS = {
    "api.congress.gov",
    "api.fiscaldata.treasury.gov",
    "api.govinfo.gov",
    "api.regulations.gov",
    "api.usaspending.gov",
    "data.sec.gov",
    "efts.sec.gov",
    "federalregister.gov",
    "www.congress.gov",
    "www.federalregister.gov",
    "www.govinfo.gov",
    "www.regulations.gov",
    "www.sec.gov",
    "www.usaspending.gov",
}
CITATION_RE = re.compile(r"\[(S\d+)\]")


class EvidenceRecord(BaseModel):
    """A bounded, source-linked fact bundle returned by every tool."""

    id: str = ""
    source: str
    title: str
    canonical_url: str
    document_id: str
    published_at: str | None = None
    retrieved_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    excerpt: str
    fields: dict[str, object] = Field(default_factory=dict)
    content_sha256: str = ""


class EvidenceRegistry:
    """Assign stable per-run citation IDs and retain evidence for rendering."""

    def __init__(self) -> None:
        self._records: list[EvidenceRecord] = []

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(self._records)

    def register(self, record: EvidenceRecord) -> EvidenceRecord:
        registered = record.model_copy(update={"id": f"S{len(self._records) + 1}"})
        self._records.append(registered)
        return registered

    def register_many(self, records: list[EvidenceRecord]) -> list[EvidenceRecord]:
        return [self.register(record) for record in records]

    def by_id(self) -> dict[str, EvidenceRecord]:
        return {record.id: record for record in self._records}


def validate_citations(answer: str, registry: EvidenceRegistry) -> list[str]:
    """Return cited IDs or fail if the answer is not grounded in registered evidence."""

    citations = CITATION_RE.findall(answer)
    known = registry.by_id()
    unknown = sorted(set(citations) - set(known))
    if unknown:
        raise CitationValidationError(f"Unknown evidence IDs in answer: {', '.join(unknown)}")
    if registry.records and not citations:
        raise CitationValidationError("The answer contains evidence but no [S#] citations")

    for citation in set(citations):
        url = known[citation].canonical_url
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS:
            raise CitationValidationError(f"Evidence {citation} does not use an official HTTPS URL")
    return citations


def render_answer(answer: str, registry: EvidenceRegistry) -> str:
    """Turn evidence markers into clickable primary-source links and append a source list."""

    validate_citations(answer, registry)
    known = registry.by_id()

    def replace(match: re.Match[str]) -> str:
        citation = match.group(1)
        return f"[{citation}]({known[citation].canonical_url})"

    linked = CITATION_RE.sub(replace, answer.strip())
    if not registry.records:
        return linked
    sources = ["", "## Sources"]
    for record in registry.records:
        sources.append(f"- [{record.id}: {record.title}]({record.canonical_url})")
    return "\n".join([linked, *sources])
