from datetime import date, datetime

import pytest

from vut_studis import client as client_module
from vut_studis.cache import CacheStore
from vut_studis.client import StudisClient
from vut_studis.config import Settings
from vut_studis.constants import PERSONAL_SCHEDULE_PATH
from vut_studis.models import ScheduleItem


def _settings() -> Settings:
    return Settings(
        VUT_BASE_URL="https://www.vut.cz",
        VUT_USERNAME="test-user",
        VUT_SESSION_COOKIE="test-session",
    )


def _item(
    name: str,
    starts_at: datetime,
    ends_at: datetime,
) -> ScheduleItem:
    return ScheduleItem(course_name=name, starts_at=starts_at, ends_at=ends_at)


@pytest.mark.asyncio
async def test_schedule_fetches_personal_path_once_and_reuses_cached_parse(
    tmp_path, monkeypatch
) -> None:
    class FakeTransport:
        def __init__(self) -> None:
            self.paths: list[str] = []

        async def get_html(self, path: str) -> str:
            self.paths.append(path)
            return "<html>schedule</html>"

    transport = FakeTransport()
    parsed_items = [_item("Lecture", datetime(2026, 5, 20, 9), datetime(2026, 5, 20, 10))]
    parse_calls: list[tuple[str, str]] = []

    def fake_parse(html: str, *, base_url: str) -> list[ScheduleItem]:
        parse_calls.append((html, base_url))
        return parsed_items

    monkeypatch.setattr(client_module, "parse_schedule_html", fake_parse)
    client = StudisClient(
        _settings(),
        cache_store=CacheStore(tmp_path / "cache.sqlite3"),
        transport=transport,  # type: ignore[arg-type]
    )

    assert await client.get_schedule() == parsed_items
    assert await client.get_schedule(date_from=date(2026, 5, 20)) == parsed_items
    assert transport.paths == [PERSONAL_SCHEDULE_PATH]
    assert parse_calls == [("<html>schedule</html>", "https://www.vut.cz/")]


@pytest.mark.asyncio
async def test_schedule_rejects_reversed_date_range_without_fetching(tmp_path) -> None:
    class FakeTransport:
        async def get_html(self, path: str) -> str:
            raise AssertionError(f"unexpected request: {path}")

    client = StudisClient(
        _settings(),
        cache_store=CacheStore(tmp_path / "cache.sqlite3"),
        transport=FakeTransport(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="date_from must not be after date_to"):
        await client.get_schedule(date_from=date(2026, 5, 21), date_to=date(2026, 5, 20))


@pytest.mark.asyncio
async def test_schedule_filters_items_that_intersect_inclusive_date_window(
    tmp_path, monkeypatch
) -> None:
    class FakeTransport:
        async def get_html(self, path: str) -> str:
            assert path == PERSONAL_SCHEDULE_PATH
            return "<html>schedule</html>"

    parsed_items = [
        _item("Previous", datetime(2026, 5, 19, 10), datetime(2026, 5, 19, 11)),
        _item("Overnight", datetime(2026, 5, 19, 23), datetime(2026, 5, 20, 1)),
        _item("Within", datetime(2026, 5, 20, 10), datetime(2026, 5, 20, 11)),
        _item("Last day", datetime(2026, 5, 21, 23), datetime(2026, 5, 22, 1)),
        _item("Following", datetime(2026, 5, 22, 10), datetime(2026, 5, 22, 11)),
    ]
    monkeypatch.setattr(
        client_module,
        "parse_schedule_html",
        lambda html, *, base_url: parsed_items,
    )
    client = StudisClient(
        _settings(),
        cache_store=CacheStore(tmp_path / "cache.sqlite3"),
        transport=FakeTransport(),  # type: ignore[arg-type]
    )

    filtered = await client.get_schedule(
        date_from=date(2026, 5, 20),
        date_to=date(2026, 5, 21),
    )

    assert [item.course_name for item in filtered] == ["Overnight", "Within", "Last day"]
    assert [item.course_name for item in await client.get_schedule(date_to=date.max)] == [
        "Previous",
        "Overnight",
        "Within",
        "Last day",
        "Following",
    ]
