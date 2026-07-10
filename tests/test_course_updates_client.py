from datetime import datetime

import pytest

from vut_studis import CourseUpdate, CourseUpdates
from vut_studis.cache import CacheStore
from vut_studis.client import StudisClient
from vut_studis.config import Settings
from vut_studis.constants import COURSE_UPDATES_PATH


def _client(tmp_path) -> StudisClient:
    return StudisClient(
        Settings(
            VUT_BASE_URL="https://www.vut.cz",
            VUT_USERNAME="test-user",
            VUT_SESSION_COOKIE="session=value",
        ),
        cache_store=CacheStore(path=tmp_path / "cache.sqlite3"),
    )


def _updates() -> CourseUpdates:
    return CourseUpdates(
        items=[
            CourseUpdate(
                id="update-3",
                published_at=datetime(2026, 7, 3, 10, 0),
                title="Newest update",
                course_code="ABC",
                course_name="Test Course",
                author="Example Teacher",
                url="https://www.vut.cz/studis/student.phtml?sn=aktualita_detail&id=3",
                course_url="https://www.vut.cz/studis/student.phtml?sn=predmet_detail&apid=3",
            ),
            CourseUpdate(
                id="update-2",
                published_at=datetime(2026, 7, 2, 10, 0),
                title="Middle update",
                course_code="ABC",
                course_name="Test Course",
                author="Example Teacher",
                url="https://www.vut.cz/studis/student.phtml?sn=aktualita_detail&id=2",
                course_url=None,
            ),
            CourseUpdate(
                id="update-1",
                published_at=datetime(2026, 7, 1, 10, 0),
                title="Oldest update",
                course_code="XYZ",
                course_name="Another Course",
                author="Another Teacher",
                url=None,
                course_url=None,
            ),
        ]
    )


@pytest.mark.asyncio
async def test_course_updates_use_one_cached_full_parse_then_slice_in_memory(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path)
    html_calls: list[str] = []
    parse_calls: list[tuple[str, str]] = []

    async def fake_get_html(path: str) -> str:
        html_calls.append(path)
        if path != COURSE_UPDATES_PATH:
            raise AssertionError(f"unexpected linked-page fetch: {path}")
        return "feed html"

    def fake_parse(html: str, *, base_url: str) -> CourseUpdates:
        parse_calls.append((html, base_url))
        return _updates()

    monkeypatch.setattr(client, "_get_html", fake_get_html)
    monkeypatch.setattr("vut_studis.client.parse_course_updates_html", fake_parse)

    limited = await client.get_course_updates(limit=1)
    full = await client.get_course_updates(limit=200)

    assert [item.id for item in limited.items] == ["update-3"]
    assert limited.truncated_count == 2
    assert [item.id for item in full.items] == ["update-3", "update-2", "update-1"]
    assert full.truncated_count == 0
    assert html_calls == [COURSE_UPDATES_PATH]
    assert parse_calls == [
        (
            "feed html",
            "https://www.vut.cz/studis/student.phtml?sn=aktuality_predmet",
        )
    ]

    await client.get_course_updates(limit=2, force_refresh=True)

    assert html_calls == [COURSE_UPDATES_PATH, COURSE_UPDATES_PATH]
    assert len(parse_calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 201, True])
async def test_course_updates_reject_invalid_limits_before_fetch(
    tmp_path,
    monkeypatch,
    limit,
) -> None:
    client = _client(tmp_path)

    async def fail_get_html(_path: str) -> str:
        raise AssertionError("invalid limit must not fetch the feed")

    monkeypatch.setattr(client, "_get_html", fail_get_html)

    with pytest.raises(ValueError, match="limit must be between 1 and 200"):
        await client.get_course_updates(limit=limit)
