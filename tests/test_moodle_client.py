from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from vut_moodle.client import MoodleClient
from vut_moodle.errors import MoodleApiError, MoodleConfigurationError
from vut_moodle.models import MoodleAssignment, MoodleCourse
from vut_studis.cache import CacheStore
from vut_studis.config import Settings


def test_moodle_settings_default_to_safe_web_fallback() -> None:
    settings = Settings(VUT_BASE_URL="https://www.vut.cz")

    assert str(settings.moodle_base_url) == "https://moodle.vut.cz/"
    assert settings.moodle_access_mode == "auto"
    assert settings.moodle_token is None
    assert settings.moodle_session_cookie is None


def test_moodle_assignment_is_frozen_and_serializable() -> None:
    assignment = MoodleAssignment(
        id=17,
        course_id=3,
        name="Project",
        url="https://moodle.vut.cz/mod/assign/view.php?id=17",
    )

    assert assignment.model_dump(mode="json")["name"] == "Project"

    with pytest.raises(ValueError):
        assignment.name = "Replacement"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "VUT_BASE_URL": "https://www.vut.cz",
        "VUT_USERNAME": "",
        "VUT_PASSWORD": "",
        "VUT_SESSION_COOKIE": "",
        "VUT_MOODLE_BASE_URL": "https://moodle.vut.cz",
        "VUT_MOODLE_ACCESS_MODE": "auto",
        "VUT_MOODLE_SESSION_COOKIE": "",
    }
    values.update({f"VUT_{key.upper()}": value for key, value in overrides.items()})
    return Settings(**values)


@pytest.mark.asyncio
@respx.mock
async def test_api_mode_returns_courses_and_assignments(tmp_path: Path) -> None:
    settings = _settings(moodle_access_mode="api", moodle_token="test-token")
    respx.post("https://moodle.vut.cz/webservice/rest/server.php").mock(
        side_effect=[
            httpx.Response(200, json={"userid": 7}),
            httpx.Response(
                200,
                json=[{"id": 42, "fullname": "Algorithms", "shortname": "ALG"}],
            ),
            httpx.Response(
                200,
                json={
                    "courses": [
                        {
                            "id": 42,
                            "assignments": [
                                {
                                    "id": 17,
                                    "name": "Project",
                                    "duedate": 1784066340,
                                    "submissionstatus": "draft",
                                    "introattachments": [],
                                }
                            ],
                        }
                    ]
                },
            ),
        ]
    )
    client = MoodleClient(settings, cache_store=CacheStore(tmp_path / "cache.sqlite3"))

    assert [course.name for course in await client.get_courses()] == ["Algorithms"]
    assignment = (await client.get_assignments())[0]
    assert assignment.due_at == datetime(2026, 7, 14, 21, 59, tzinfo=UTC)
    assert assignment.submission_status == "draft"


@pytest.mark.asyncio
async def test_api_mode_requires_an_explicit_token() -> None:
    with pytest.raises(MoodleConfigurationError, match="VUT_MOODLE_TOKEN"):
        await MoodleClient(_settings(moodle_access_mode="api")).get_courses()


@pytest.mark.asyncio
async def test_auto_mode_falls_back_to_web_after_api_error(tmp_path: Path, monkeypatch) -> None:
    client = MoodleClient(
        _settings(moodle_access_mode="auto", moodle_token="test-token"),
        cache_store=CacheStore(tmp_path / "cache.sqlite3"),
    )

    async def unavailable_api() -> list[MoodleCourse]:
        raise MoodleApiError("core_enrol_get_users_courses", "Forbidden")

    async def web_courses() -> list[MoodleCourse]:
        return [
            MoodleCourse(
                id=1,
                name="Algorithms",
                url="https://moodle.vut.cz/course/view.php?id=1",
            )
        ]

    monkeypatch.setattr(client, "_fetch_courses_api", unavailable_api)
    monkeypatch.setattr(client, "_fetch_courses_web", web_courses)

    assert [course.id for course in await client.get_courses()] == [1]


@pytest.mark.asyncio
async def test_moodle_courses_are_cached_by_source_and_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(moodle_access_mode="web", cache_path=tmp_path / "cache.sqlite3")
    client = MoodleClient(settings)
    calls = 0

    async def fetch_courses() -> list[MoodleCourse]:
        nonlocal calls
        calls += 1
        return [
            MoodleCourse(
                id=1,
                name="Algorithms",
                url="https://moodle.vut.cz/course/view.php?id=1",
            )
        ]

    monkeypatch.setattr(client, "_fetch_courses_web", fetch_courses)

    assert await client.get_courses() == await client.get_courses()
    assert calls == 1
