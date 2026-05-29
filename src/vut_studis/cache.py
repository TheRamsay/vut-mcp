from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
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
    state_snapshots: int
    delivered_notifications: int
    dismissed_actions: int
    course_notes: int
    size_bytes: int


@dataclass(frozen=True)
class _CacheEntry:
    payload_json: str
    fetched_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class StateSnapshot:
    resource_type: str
    resource_id: str
    payload_json: str | None
    payload_hash: str | None
    captured_at: datetime
    is_deleted: bool


@dataclass(frozen=True)
class StoredCourseNote:
    note_id: str
    course_code: str
    body: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredDismissedAction:
    action_id: str
    reason: str | None
    dismissed_at: datetime


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
            removed = cursor.rowcount
            cursor = connection.execute("DELETE FROM state_snapshots")
            removed += cursor.rowcount
            cursor = connection.execute("DELETE FROM delivered_notifications")
            removed += cursor.rowcount
            cursor = connection.execute("DELETE FROM dismissed_actions")
            removed += cursor.rowcount
            cursor = connection.execute("DELETE FROM course_notes")
            return removed + cursor.rowcount

    def delete(self, key: str) -> None:
        if self.disabled or not self.path.exists():
            return

        with self._connection() as connection:
            connection.execute("DELETE FROM cache_entries WHERE key = ?", (key,))

    def get_latest_state_snapshots(
        self,
        *,
        scope: str,
        resource_type: str,
    ) -> dict[str, StateSnapshot]:
        if self.disabled or not self.path.exists():
            return {}

        snapshots: dict[str, StateSnapshot] = {}
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    resource_type,
                    resource_id,
                    payload_json,
                    payload_hash,
                    captured_at,
                    is_deleted
                FROM state_snapshots
                WHERE scope = ? AND resource_type = ?
                ORDER BY resource_id ASC, captured_at DESC, id DESC
                """,
                (scope, resource_type),
            ).fetchall()

        for row in rows:
            resource_id = row["resource_id"]
            if resource_id in snapshots:
                continue
            snapshots[resource_id] = StateSnapshot(
                resource_type=row["resource_type"],
                resource_id=resource_id,
                payload_json=row["payload_json"],
                payload_hash=row["payload_hash"],
                captured_at=_from_iso(row["captured_at"]),
                is_deleted=bool(row["is_deleted"]),
            )

        return snapshots

    def record_state_snapshot(
        self,
        *,
        scope: str,
        resource_type: str,
        resource_id: str,
        payload_json: str | None,
        captured_at: datetime,
        is_deleted: bool = False,
    ) -> None:
        if self.disabled:
            return

        payload_hash = sha256(payload_json.encode("utf-8")).hexdigest() if payload_json else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO state_snapshots (
                    scope,
                    resource_type,
                    resource_id,
                    payload_json,
                    payload_hash,
                    captured_at,
                    is_deleted
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope,
                    resource_type,
                    resource_id,
                    payload_json,
                    payload_hash,
                    _to_iso(captured_at),
                    int(is_deleted),
                ),
            )

    def get_delivered_notification_ids(
        self,
        *,
        scope: str,
        notification_ids: Sequence[str],
    ) -> set[str]:
        if self.disabled or not self.path.exists() or not notification_ids:
            return set()

        placeholders = ",".join("?" for _ in notification_ids)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT notification_id
                FROM delivered_notifications
                WHERE scope = ? AND notification_id IN ({placeholders})
                """,
                (scope, *notification_ids),
            ).fetchall()

        return {str(row["notification_id"]) for row in rows}

    def record_delivered_notifications(
        self,
        *,
        scope: str,
        notification_ids: Sequence[str],
        delivered_at: datetime | None = None,
    ) -> None:
        if self.disabled or not notification_ids:
            return

        delivered_at = delivered_at or _utc_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO delivered_notifications (
                    scope,
                    notification_id,
                    delivered_at
                )
                VALUES (?, ?, ?)
                """,
                [
                    (scope, notification_id, _to_iso(delivered_at))
                    for notification_id in notification_ids
                ],
            )

    def dismiss_action(
        self,
        *,
        scope: str,
        action_id: str,
        reason: str | None = None,
        dismissed_at: datetime | None = None,
    ) -> StoredDismissedAction:
        dismissed_at = dismissed_at or _utc_now()
        if self.disabled:
            return StoredDismissedAction(
                action_id=action_id,
                reason=reason,
                dismissed_at=dismissed_at,
            )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO dismissed_actions (
                    scope,
                    action_id,
                    reason,
                    dismissed_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope, action_id) DO UPDATE SET
                    reason = excluded.reason,
                    dismissed_at = excluded.dismissed_at
                """,
                (scope, action_id, reason, _to_iso(dismissed_at)),
            )

        return StoredDismissedAction(
            action_id=action_id,
            reason=reason,
            dismissed_at=dismissed_at,
        )

    def get_dismissed_action_ids(
        self,
        *,
        scope: str,
        action_ids: Sequence[str],
    ) -> set[str]:
        if self.disabled or not self.path.exists() or not action_ids:
            return set()

        placeholders = ",".join("?" for _ in action_ids)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT action_id
                FROM dismissed_actions
                WHERE scope = ? AND action_id IN ({placeholders})
                """,
                (scope, *action_ids),
            ).fetchall()

        return {str(row["action_id"]) for row in rows}

    def add_course_note(
        self,
        *,
        scope: str,
        note_id: str,
        course_code: str,
        body: str,
        created_at: datetime | None = None,
    ) -> StoredCourseNote:
        created_at = created_at or _utc_now()
        if self.disabled:
            return StoredCourseNote(
                note_id=note_id,
                course_code=course_code,
                body=body,
                created_at=created_at,
                updated_at=created_at,
            )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        normalized_code = course_code.upper()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO course_notes (
                    scope,
                    note_id,
                    course_code,
                    body,
                    created_at,
                    updated_at,
                    archived
                )
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    scope,
                    note_id,
                    normalized_code,
                    body,
                    _to_iso(created_at),
                    _to_iso(created_at),
                ),
            )

        return StoredCourseNote(
            note_id=note_id,
            course_code=normalized_code,
            body=body,
            created_at=created_at,
            updated_at=created_at,
        )

    def list_course_notes(
        self,
        *,
        scope: str,
        course_code: str | None = None,
    ) -> list[StoredCourseNote]:
        if self.disabled or not self.path.exists():
            return []

        parameters: tuple[str, ...]
        if course_code is None:
            where = "scope = ? AND archived = 0"
            parameters = (scope,)
        else:
            where = "scope = ? AND course_code = ? AND archived = 0"
            parameters = (scope, course_code.upper())

        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT note_id, course_code, body, created_at, updated_at
                FROM course_notes
                WHERE {where}
                ORDER BY updated_at DESC, created_at DESC
                """,
                parameters,
            ).fetchall()

        return [
            StoredCourseNote(
                note_id=row["note_id"],
                course_code=row["course_code"],
                body=row["body"],
                created_at=_from_iso(row["created_at"]),
                updated_at=_from_iso(row["updated_at"]),
            )
            for row in rows
        ]

    def status(self) -> CacheStatus:
        if self.disabled or not self.path.exists():
            return CacheStatus(
                path=self.path,
                enabled=not self.disabled,
                entries=0,
                expired_entries=0,
                state_snapshots=0,
                delivered_notifications=0,
                dismissed_actions=0,
                course_notes=0,
                size_bytes=0,
            )

        now_iso = _to_iso(_utc_now())
        with self._connection() as connection:
            entries = connection.execute("SELECT count(*) FROM cache_entries").fetchone()[0]
            expired_entries = connection.execute(
                "SELECT count(*) FROM cache_entries WHERE expires_at <= ?",
                (now_iso,),
            ).fetchone()[0]
            state_snapshots = connection.execute(
                "SELECT count(*) FROM state_snapshots",
            ).fetchone()[0]
            delivered_notifications = connection.execute(
                "SELECT count(*) FROM delivered_notifications",
            ).fetchone()[0]
            dismissed_actions = connection.execute(
                "SELECT count(*) FROM dismissed_actions",
            ).fetchone()[0]
            course_notes = connection.execute(
                "SELECT count(*) FROM course_notes WHERE archived = 0",
            ).fetchone()[0]

        return CacheStatus(
            path=self.path,
            enabled=True,
            entries=entries,
            expired_entries=expired_entries,
            state_snapshots=state_snapshots,
            delivered_notifications=delivered_notifications,
            dismissed_actions=dismissed_actions,
            course_notes=course_notes,
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS state_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                payload_json TEXT,
                payload_hash TEXT,
                captured_at TEXT NOT NULL,
                is_deleted INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_state_snapshots_latest
            ON state_snapshots(scope, resource_type, resource_id, captured_at DESC)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS delivered_notifications (
                scope TEXT NOT NULL,
                notification_id TEXT NOT NULL,
                delivered_at TEXT NOT NULL,
                PRIMARY KEY (scope, notification_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS dismissed_actions (
                scope TEXT NOT NULL,
                action_id TEXT NOT NULL,
                reason TEXT,
                dismissed_at TEXT NOT NULL,
                PRIMARY KEY (scope, action_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS course_notes (
                scope TEXT NOT NULL,
                note_id TEXT NOT NULL,
                course_code TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (scope, note_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_course_notes_course
            ON course_notes(scope, course_code, archived, updated_at DESC)
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
