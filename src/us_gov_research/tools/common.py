"""Shared normalization helpers for source adapters."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from us_gov_research.evidence import EvidenceRecord

MAX_EXCERPT_CHARS = 12_000


def clean_text(value: object, *, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > max_chars:
        return f"{text[: max_chars - 1].rstrip()}…"
    return text


def relevant_excerpt(text: str, query: str, *, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    cleaned = clean_text(text, max_chars=max(len(text), max_chars))
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9-]{3,}", query)][:8]
    lower = cleaned.lower()
    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
    if not positions:
        return clean_text(cleaned, max_chars=max_chars)
    start = max(0, min(positions) - max_chars // 5)
    return clean_text(cleaned[start : start + max_chars], max_chars=max_chars)


def evidence(
    *,
    source: str,
    title: object,
    canonical_url: str,
    document_id: object,
    excerpt: object,
    published_at: object = None,
    fields: dict[str, Any] | None = None,
) -> EvidenceRecord:
    normalized_excerpt = clean_text(excerpt)
    digest_payload = json.dumps(
        [source, str(document_id), canonical_url, normalized_excerpt],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return EvidenceRecord(
        source=source,
        title=clean_text(title, max_chars=500),
        canonical_url=canonical_url,
        document_id=clean_text(document_id, max_chars=300),
        published_at=str(published_at) if published_at else None,
        excerpt=normalized_excerpt,
        fields=fields or {},
        content_sha256=hashlib.sha256(digest_payload.encode()).hexdigest(),
    )
