import pytest

from vut_studis.cache import CacheStore
from vut_studis.client import StudisClient
from vut_studis.config import Settings
from vut_studis.models import ChangeKind, Grade


def _client(tmp_path) -> StudisClient:
    return StudisClient(
        Settings(
            VUT_BASE_URL="https://www.vut.cz",
            VUT_USERNAME="test-user",
            VUT_SESSION_COOKIE="session=value",
        ),
        cache_store=CacheStore(path=tmp_path / "cache.sqlite3"),
    )


@pytest.mark.asyncio
async def test_recent_changes_can_skip_pending_action_scan(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path)
    grades = [
        Grade(
            course_code="ABC",
            course_name="Test Course",
            academic_year="2025/26",
            semester="L",
            points=10,
        )
    ]

    async def fake_get_grades(*, force_refresh: bool = False) -> list[Grade]:
        assert force_refresh is True
        return grades

    async def fail_get_pending_actions(**_kwargs):
        raise AssertionError("pending actions should not be fetched")

    monkeypatch.setattr(client, "get_grades", fake_get_grades)
    monkeypatch.setattr(client, "get_pending_actions", fail_get_pending_actions)

    baseline = await client.get_recent_changes(
        force_refresh=True,
        include_pending_actions=False,
    )
    grades = [grades[0].model_copy(update={"points": 12})]
    changes = await client.get_recent_changes(
        force_refresh=True,
        include_pending_actions=False,
    )

    assert baseline.baseline_created is True
    assert baseline.changes == []
    actual_changes = [
        (change.kind, change.resource_type, change.resource_id) for change in changes.changes
    ]
    assert actual_changes == [
        (ChangeKind.UPDATED, "grade", "2025/26:L:ABC")
    ]
    assert changes.changes[0].changed_fields == ["points"]
