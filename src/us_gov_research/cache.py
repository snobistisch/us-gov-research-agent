"""Small local SQLite cache for official API responses."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_path


@dataclass(frozen=True)
class CacheEntry:
    body: bytes
    content_type: str


class ResponseCache:
    """A process-safe-enough cache for a single-user CLI."""

    def __init__(self, path: Path | None = None) -> None:
        cache_dir = path.parent if path else user_cache_path("us-gov-research-agent")
        cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path or cache_dir / "responses.sqlite3"
        self._connection = sqlite3.connect(self.path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS responses (
                cache_key TEXT PRIMARY KEY,
                body BLOB NOT NULL,
                content_type TEXT NOT NULL,
                expires_at REAL NOT NULL,
                stored_at REAL NOT NULL
            )
            """
        )
        self._connection.commit()

    def get(self, cache_key: str) -> CacheEntry | None:
        row = self._connection.execute(
            "SELECT body, content_type, expires_at FROM responses WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        body, content_type, expires_at = row
        if expires_at < time.time():
            self._connection.execute("DELETE FROM responses WHERE cache_key = ?", (cache_key,))
            self._connection.commit()
            return None
        return CacheEntry(body=body, content_type=content_type)

    def set(self, cache_key: str, body: bytes, content_type: str, ttl_seconds: int) -> None:
        now = time.time()
        self._connection.execute(
            """
            INSERT INTO responses(cache_key, body, content_type, expires_at, stored_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                body = excluded.body,
                content_type = excluded.content_type,
                expires_at = excluded.expires_at,
                stored_at = excluded.stored_at
            """,
            (cache_key, body, content_type, now + ttl_seconds, now),
        )
        self._connection.commit()

    def clear(self) -> None:
        self._connection.execute("DELETE FROM responses")
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()
