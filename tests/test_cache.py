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


def test_empty_cache_path_uses_default() -> None:
    settings = Settings(VUT_BASE_URL="https://www.vut.cz", VUT_CACHE_PATH="")

    assert settings.cache_path is None
