from __future__ import annotations

import pytest

from us_gov_research.errors import CitationValidationError
from us_gov_research.evidence import EvidenceRecord, EvidenceRegistry, render_answer


def record(url: str = "https://www.sec.gov/example") -> EvidenceRecord:
    return EvidenceRecord(
        source="sec",
        title="Primary filing",
        canonical_url=url,
        document_id="abc",
        excerpt="A supported fact.",
    )


def test_registry_and_renderer_link_known_evidence() -> None:
    registry = EvidenceRegistry()
    registered = registry.register(record())

    rendered = render_answer("The filing reports a fact. [S1]", registry)

    assert registered.id == "S1"
    assert "[S1](https://www.sec.gov/example)" in rendered
    assert "## Sources" in rendered


def test_renderer_rejects_unknown_id() -> None:
    registry = EvidenceRegistry()
    registry.register(record())

    with pytest.raises(CitationValidationError, match="Unknown evidence"):
        render_answer("Unsupported. [S2]", registry)


def test_renderer_rejects_non_official_host() -> None:
    registry = EvidenceRegistry()
    registry.register(record("https://example.org/not-primary"))

    with pytest.raises(CitationValidationError, match="official HTTPS"):
        render_answer("Claim. [S1]", registry)
