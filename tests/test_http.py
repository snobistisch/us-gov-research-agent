from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from us_gov_research.cache import ResponseCache
from us_gov_research.errors import BudgetExceeded, SourceError
from us_gov_research.http import GovernmentClient, RequestBudget, build_rate_limiters


@pytest.mark.asyncio
async def test_cache_avoids_duplicate_request(tmp_path: Path) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"ok": True})

    cache = ResponseCache(tmp_path / "cache.sqlite3")
    client = GovernmentClient(
        budget=RequestBudget(2),
        cache=cache,
        transport=httpx.MockTransport(handler),
    )
    try:
        first = await client.get_json(
            "treasury",
            "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/example",
        )
        second = await client.get_json(
            "treasury",
            "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/example",
        )
    finally:
        await client.close()

    assert first == second == {"ok": True}
    assert calls == 1


def test_cache_key_excludes_credentials() -> None:
    one = GovernmentClient._cache_key(
        "govinfo",
        "GET",
        "https://api.govinfo.gov/search",
        {"api_key": "first-secret", "query": "budget"},
        None,
        {"Authorization": "Bearer first-secret"},
    )
    two = GovernmentClient._cache_key(
        "govinfo",
        "GET",
        "https://api.govinfo.gov/search",
        {"api_key": "second-secret", "query": "budget"},
        None,
        {"Authorization": "Bearer second-secret"},
    )

    assert one == two
    assert "secret" not in one


@pytest.mark.asyncio
async def test_budget_is_checked_before_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"ok": True}))

    client = GovernmentClient(
        budget=RequestBudget(0), cache=None, transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(BudgetExceeded):
            await client.get_json(
                "treasury",
                "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/example",
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_non_allowlisted_host_is_blocked() -> None:
    client = GovernmentClient(budget=RequestBudget(1), cache=None)
    try:
        with pytest.raises(SourceError, match="non-allowlisted"):
            await client.get_json("sec", "https://example.com/steal")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_clients_can_share_source_rate_limiters() -> None:
    shared = build_rate_limiters()
    first = GovernmentClient(budget=RequestBudget(1), cache=None, limiters=shared)
    second = GovernmentClient(budget=RequestBudget(1), cache=None, limiters=shared)
    try:
        assert first._limiters is shared
        assert second._limiters is shared
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_sec_403_has_actionable_redacted_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    client = GovernmentClient(
        budget=RequestBudget(1),
        cache=None,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(SourceError) as caught:
            await client.get_json(
                "sec",
                "https://data.sec.gov/submissions/CIK0001318605.json",
                headers={"User-Agent": "Private Identity private@valid.test"},
            )
    finally:
        await client.close()

    message = str(caught.value)
    assert "HTTP 403" in message
    assert "Check SEC_USER_AGENT" in message
    assert "private@valid.test" not in message
