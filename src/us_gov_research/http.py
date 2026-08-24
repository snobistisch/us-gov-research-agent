"""Allowlisted HTTP, request budgets, throttling, retry, and caching."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from .cache import ResponseCache
from .errors import BudgetExceeded, SourceError

ALLOWED_HOSTS: dict[str, set[str]] = {
    "sec": {"data.sec.gov", "www.sec.gov", "efts.sec.gov"},
    "congress": {"api.congress.gov"},
    "federal_register": {"www.federalregister.gov"},
    "usaspending": {"api.usaspending.gov"},
    "treasury": {"api.fiscaldata.treasury.gov"},
    "regulations": {"api.regulations.gov"},
    "govinfo": {"api.govinfo.gov"},
}

REQUESTS_PER_SECOND = {
    "sec": 5.0,
    "congress": 1.0,
    "federal_register": 2.0,
    "usaspending": 1.0,
    "treasury": 2.0,
    "regulations": 0.25,
    "govinfo": 5.0,
}

TRANSIENT_STATUS = {429, 502, 503, 504}
SENSITIVE_NAMES = {"api_key", "apikey", "key", "token", "authorization", "x-api-key"}


@dataclass
class RequestBudget:
    limit: int
    used: int = 0

    def consume(self) -> None:
        if self.used >= self.limit:
            raise BudgetExceeded(f"Government HTTP request limit of {self.limit} reached")
        self.used += 1


class AsyncRateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self.interval = 1 / requests_per_second
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait_for = max(0.0, self._next_at - now)
            if wait_for:
                await asyncio.sleep(wait_for)
            self._next_at = max(now, self._next_at) + self.interval


class GovernmentClient:
    """HTTP client that only talks to configured official hosts."""

    def __init__(
        self,
        *,
        budget: RequestBudget,
        cache: ResponseCache | None,
        refresh: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        limiters: dict[str, AsyncRateLimiter] | None = None,
    ) -> None:
        self.budget = budget
        self.cache = cache
        self.refresh = refresh
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
            transport=transport,
            headers={"Accept-Encoding": "gzip, deflate"},
        )
        self._limiters = limiters or build_rate_limiters()

    async def __aenter__(self) -> GovernmentClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()
        if self.cache is not None:
            self.cache.close()

    async def get_json(self, source: str, url: str, **kwargs: Any) -> dict[str, Any]:
        body = await self.request(source, "GET", url, **kwargs)
        try:
            value = json.loads(body)
        except json.JSONDecodeError as exc:
            raise SourceError(source, "official API returned invalid JSON", retryable=True) from exc
        if not isinstance(value, dict):
            raise SourceError(source, "official API returned an unexpected JSON shape")
        return value

    async def post_json(self, source: str, url: str, **kwargs: Any) -> dict[str, Any]:
        body = await self.request(source, "POST", url, **kwargs)
        try:
            value = json.loads(body)
        except json.JSONDecodeError as exc:
            raise SourceError(source, "official API returned invalid JSON", retryable=True) from exc
        if not isinstance(value, dict):
            raise SourceError(source, "official API returned an unexpected JSON shape")
        return value

    async def get_text(self, source: str, url: str, **kwargs: Any) -> str:
        body = await self.request(source, "GET", url, **kwargs)
        return body.decode("utf-8", errors="replace")

    async def request(
        self,
        source: str,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        ttl_seconds: int = 3600,
        max_bytes: int = 20 * 1024 * 1024,
    ) -> bytes:
        self._assert_allowed(source, url, method)
        cache_key = self._cache_key(source, method, url, params, json_body, headers)
        if not self.refresh and self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached.body

        last_error: Exception | None = None
        for attempt in range(3):
            await self._limiters[source].wait()
            self.budget.consume()
            try:
                async with self._client.stream(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                ) as response:
                    if response.status_code in TRANSIENT_STATUS:
                        if attempt < 2:
                            await asyncio.sleep(self._retry_delay(response, attempt))
                            continue
                        raise SourceError(
                            source,
                            f"official API remained unavailable (HTTP {response.status_code})",
                            retryable=True,
                        )
                    if response.status_code >= 400:
                        raise SourceError(
                            source,
                            f"official API rejected the request (HTTP {response.status_code})",
                            retryable=False,
                        )

                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise SourceError(source, f"response exceeded {max_bytes} bytes")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    if self.cache is not None and ttl_seconds > 0:
                        self.cache.set(
                            cache_key,
                            body,
                            response.headers.get("content-type", "application/octet-stream"),
                            ttl_seconds,
                        )
                    return body
            except SourceError:
                raise
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep((2**attempt) + random.random())
                    continue
        raise SourceError(
            source, "network request failed after retries", retryable=True
        ) from last_error

    @staticmethod
    def _assert_allowed(source: str, url: str, method: str) -> None:
        parsed = urlparse(url)
        if source not in ALLOWED_HOSTS:
            raise SourceError(source, "unknown source adapter")
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS[source]:
            raise SourceError(source, "adapter attempted a non-allowlisted URL")
        if method not in {"GET", "POST"}:
            raise SourceError(source, "adapter attempted a non-read operation")
        if method == "POST" and source not in {"usaspending", "govinfo"}:
            raise SourceError(source, "POST is not allowlisted for this source")

    @staticmethod
    def _cache_key(
        source: str,
        method: str,
        url: str,
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
        headers: dict[str, str] | None,
    ) -> str:
        safe_params = {
            key: value
            for key, value in sorted((params or {}).items())
            if key.lower() not in SENSITIVE_NAMES
        }
        safe_headers = {
            key.lower(): value
            for key, value in sorted((headers or {}).items())
            if key.lower() not in SENSITIVE_NAMES and key.lower() != "user-agent"
        }
        canonical = json.dumps(
            [source, method, url, safe_params, json_body or {}, safe_headers],
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                try:
                    seconds = parsedate_to_datetime(retry_after).timestamp() - time.time()
                    return max(0.0, min(seconds, 60.0))
                except (TypeError, ValueError, OverflowError):
                    pass
        return min((2**attempt) + random.random(), 10.0)


def build_rate_limiters() -> dict[str, AsyncRateLimiter]:
    """Build a complete limiter set that can be shared across parallel clients."""

    return {source: AsyncRateLimiter(rate) for source, rate in REQUESTS_PER_SECOND.items()}
