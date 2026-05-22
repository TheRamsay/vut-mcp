from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from vut_studis.config import Settings


@dataclass(frozen=True)
class CacheMeta:
    source: Literal["cache", "live"]
    fetched_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class Cached[T]:
    value: T
    meta: CacheMeta


@dataclass(frozen=True)
class CacheStatus:
    path: Path
    enabled: bool
    entries: int
    expired_entries: int
    size_bytes: int


@dataclass(frozen=True)
class _CacheEntry:
    payload_json: str
    fetched_at: datetime
    expires_at: datetime


class CacheStore:
    def __init__(self, path: Path | None = None, *, disabled: bool = False) -> None:
        self.path = path or default_cache_path()
        self.disabled = disabled

    @classmethod
    def from_settings(cls, settings: Settings) -> CacheStore:
        return cls(path=settings.cache_path, disabled=settings.cache_disabled)

    async def get_or_fetch[T](
        self,
        *,
        key: str,
        resource_type: str,
        ttl: timedelta,
        force_refresh: bool,
        fetch: Callable[[], Awaitable[T]],
        encode: Callable[[T], str],
        decode: Callable[[str], T],
    ) -> Cached[T]:
        now = _utc_now()

        if not self.disabled and not force_refresh:
            entry = self._get_entry(key)
            if entry is not None and entry.expires_at > now:
                try:
                    value = decode(entry.payload_json)
                except (json.JSONDecodeError, ValueError, TypeError):
                    self.delete(key)
                else:
                    return Cached(
                        value=value,
                        meta=CacheMeta(
                            source="cache",
                            fetched_at=entry.fetched_at,
                            expires_at=entry.expires_at,
                        ),
                    )

        value = await fetch()
        fetched_at = _utc_now()
        expires_at = fetched_at + ttl

        if not self.disabled:
            self._set_entry(
                key=key,
                resource_type=resource_type,
                payload_json=encode(value),
                fetched_at=fetched_at,
                expires_at=expires_at,
            )

        return Cached(
            value=value,
            meta=CacheMeta(source="live", fetched_at=fetched_at, expires_at=expires_at),
        )

    def clear(self) -> int:
        if self.disabled or not self.path.exists():
            return 0

        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM cache_entries")
            return cursor.rowcount

    def delete(self, key: str) -> None:
        if self.disabled or not self.path.exists():
            return

        with self._connection() as connection:
            connection.execute("DELETE FROM cache_entries WHERE key = ?", (key,))

    def status(self) -> CacheStatus:
        if self.disabled or not self.path.exists():
            return CacheStatus(
                path=self.path,
                enabled=not self.disabled,
                entries=0,
                expired_entries=0,
                size_bytes=0,
            )

        now_iso = _to_iso(_utc_now())
        with self._connection() as connection:
            entries = connection.execute("SELECT count(*) FROM cache_entries").fetchone()[0]
            expired_entries = connection.execute(
                "SELECT count(*) FROM cache_entries WHERE expires_at <= ?",
                (now_iso,),
            ).fetchone()[0]

        return CacheStatus(
            path=self.path,
            enabled=True,
            entries=entries,
            expired_entries=expired_entries,
            size_bytes=self.path.stat().st_size,
        )

    def _get_entry(self, key: str) -> _CacheEntry | None:
        if not self.path.exists():
            return None

        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json, fetched_at, expires_at
                FROM cache_entries
                WHERE key = ?
                """,
                (key,),
            ).fetchone()

        if row is None:
            return None

        try:
            return _CacheEntry(
                payload_json=row["payload_json"],
                fetched_at=_from_iso(row["fetched_at"]),
                expires_at=_from_iso(row["expires_at"]),
            )
        except ValueError:
            self.delete(key)
            return None

    def _set_entry(
        self,
        *,
        key: str,
        resource_type: str,
        payload_json: str,
        fetched_at: datetime,
        expires_at: datetime,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO cache_entries (
                    key,
                    resource_type,
                    payload_json,
                    fetched_at,
                    expires_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    resource_type = excluded.resource_type,
                    payload_json = excluded.payload_json,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                """,
                (key, resource_type, payload_json, _to_iso(fetched_at), _to_iso(expires_at)),
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                key TEXT PRIMARY KEY,
                resource_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cache_entries_resource_type
            ON cache_entries(resource_type)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cache_entries_expires_at
            ON cache_entries(expires_at)
            """
        )
        return connection


def default_cache_path() -> Path:
    cache_root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return cache_root / "vut-mcp" / "cache.sqlite3"


def encode_model(model: BaseModel) -> str:
    return model.model_dump_json()


def decode_model[M: BaseModel](payload_json: str, model_type: type[M]) -> M:
    return model_type.model_validate_json(payload_json)


def encode_model_list(models: Sequence[BaseModel]) -> str:
    return json.dumps([model.model_dump(mode="json") for model in models], ensure_ascii=False)


def decode_model_list[M: BaseModel](payload_json: str, model_type: type[M]) -> list[M]:
    payload = json.loads(payload_json)
    if not isinstance(payload, list):
        raise ValueError("Cached payload is not a list.")
    return [model_type.model_validate(item) for item in payload]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
