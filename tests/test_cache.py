from datetime import UTC, datetime, timedelta

import pytest

from vut_studis.cache import CacheStore, decode_model_list, encode_model_list
from vut_studis.config import Settings
from vut_studis.models import Grade, GradeValue


def _grade(points: float) -> Grade:
    return Grade(course_code="ABC", course_name="Test Course", grade=GradeValue.A, points=points)


@pytest.mark.asyncio
async def test_cache_hit_skips_fetch(tmp_path) -> None:
    store = CacheStore(tmp_path / "cache.sqlite3")
    calls = 0

    async def fetch() -> list[Grade]:
        nonlocal calls
        calls += 1
        return [_grade(91)]

    first = await store.get_or_fetch(
        key="grades:test",
        resource_type="grades",
        ttl=timedelta(minutes=5),
        force_refresh=False,
        fetch=fetch,
        encode=encode_model_list,
        decode=lambda payload: decode_model_list(payload, Grade),
    )
    second = await store.get_or_fetch(
        key="grades:test",
        resource_type="grades",
        ttl=timedelta(minutes=5),
        force_refresh=False,
        fetch=fetch,
        encode=encode_model_list,
        decode=lambda payload: decode_model_list(payload, Grade),
    )

    assert calls == 1
    assert first.meta.source == "live"
    assert second.meta.source == "cache"
    assert second.value == [_grade(91)]


@pytest.mark.asyncio
async def test_expired_cache_refetches(tmp_path) -> None:
    store = CacheStore(tmp_path / "cache.sqlite3")
    calls = 0

    async def fetch() -> list[Grade]:
        nonlocal calls
        calls += 1
        return [_grade(90 + calls)]

    await store.get_or_fetch(
        key="grades:test",
        resource_type="grades",
        ttl=timedelta(seconds=-1),
        force_refresh=False,
        fetch=fetch,
        encode=encode_model_list,
        decode=lambda payload: decode_model_list(payload, Grade),
    )
    second = await store.get_or_fetch(
        key="grades:test",
        resource_type="grades",
        ttl=timedelta(minutes=5),
        force_refresh=False,
        fetch=fetch,
        encode=encode_model_list,
        decode=lambda payload: decode_model_list(payload, Grade),
    )

    assert calls == 2
    assert second.meta.source == "live"
    assert second.value == [_grade(92)]


@pytest.mark.asyncio
async def test_force_refresh_ignores_valid_cache(tmp_path) -> None:
    store = CacheStore(tmp_path / "cache.sqlite3")
    calls = 0

    async def fetch() -> list[Grade]:
        nonlocal calls
        calls += 1
        return [_grade(80 + calls)]

    await store.get_or_fetch(
        key="grades:test",
        resource_type="grades",
        ttl=timedelta(minutes=5),
        force_refresh=False,
        fetch=fetch,
        encode=encode_model_list,
        decode=lambda payload: decode_model_list(payload, Grade),
    )
    second = await store.get_or_fetch(
        key="grades:test",
        resource_type="grades",
        ttl=timedelta(minutes=5),
        force_refresh=True,
        fetch=fetch,
        encode=encode_model_list,
        decode=lambda payload: decode_model_list(payload, Grade),
    )

    assert calls == 2
    assert second.meta.source == "live"
    assert second.value == [_grade(82)]


@pytest.mark.asyncio
async def test_corrupted_payload_is_deleted_and_refetched(tmp_path) -> None:
    store = CacheStore(tmp_path / "cache.sqlite3")
    store._set_entry(
        key="grades:test",
        resource_type="grades",
        payload_json="{bad json",
        fetched_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    calls = 0

    async def fetch() -> list[Grade]:
        nonlocal calls
        calls += 1
        return [_grade(75)]

    result = await store.get_or_fetch(
        key="grades:test",
        resource_type="grades",
        ttl=timedelta(minutes=5),
        force_refresh=False,
        fetch=fetch,
        encode=encode_model_list,
        decode=lambda payload: decode_model_list(payload, Grade),
    )

    assert calls == 1
    assert result.meta.source == "live"
    assert result.value == [_grade(75)]


def test_cache_status_and_clear(tmp_path) -> None:
    store = CacheStore(tmp_path / "cache.sqlite3")
    store._set_entry(
        key="grades:test",
        resource_type="grades",
        payload_json="[]",
        fetched_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    status = store.status()
    removed = store.clear()

    assert status.enabled is True
    assert status.entries == 1
    assert status.size_bytes > 0
    assert removed == 1
    assert store.status().entries == 0


def test_delivered_notification_dedupe(tmp_path) -> None:
    store = CacheStore(tmp_path / "cache.sqlite3")

    assert store.get_delivered_notification_ids(
        scope="test",
        notification_ids=["a", "b"],
    ) == set()

    store.record_delivered_notifications(scope="test", notification_ids=["a"])

    assert store.get_delivered_notification_ids(
        scope="test",
        notification_ids=["a", "b"],
    ) == {"a"}
    assert store.status().delivered_notifications == 1


def test_dismissed_actions_are_scoped_and_deduped(tmp_path) -> None:
    store = CacheStore(tmp_path / "cache.sqlite3")
    dismissed_at = datetime(2026, 5, 29, 8, 0, tzinfo=UTC)

    dismissed = store.dismiss_action(
        scope="test",
        action_id="action-1",
        reason="not relevant",
        dismissed_at=dismissed_at,
    )
    store.dismiss_action(scope="other", action_id="action-2", dismissed_at=dismissed_at)

    assert dismissed.action_id == "action-1"
    assert store.get_dismissed_action_ids(
        scope="test",
        action_ids=["action-1", "action-2"],
    ) == {"action-1"}


def test_course_notes_are_scoped_and_filterable(tmp_path) -> None:
    store = CacheStore(tmp_path / "cache.sqlite3")
    created_at = datetime(2026, 5, 29, 8, 0, tzinfo=UTC)

    store.add_course_note(
        scope="test",
        note_id="note-1",
        course_code="flp",
        body="Check exam registration.",
        created_at=created_at,
    )
    store.add_course_note(
        scope="test",
        note_id="note-2",
        course_code="SUR",
        body="Read Moodle.",
        created_at=created_at + timedelta(minutes=1),
    )

    assert [note.course_code for note in store.list_course_notes(scope="test")] == ["SUR", "FLP"]
    assert [note.body for note in store.list_course_notes(scope="test", course_code="FLP")] == [
        "Check exam registration."
    ]


def test_empty_cache_path_uses_default() -> None:
    settings = Settings(VUT_BASE_URL="https://www.vut.cz", VUT_CACHE_PATH="")

    assert settings.cache_path is None
