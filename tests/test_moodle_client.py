from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

from vut_moodle.client import MoodleClient
from vut_moodle.errors import (
    MoodleApiError,
    MoodleConfigurationError,
    MoodleContentError,
    MoodleDataError,
)
from vut_moodle.models import MoodleAssignment, MoodleCourse, MoodleCourseResource, MoodleFile
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


def test_moodle_course_resource_is_frozen_and_serializable() -> None:
    resource = MoodleCourseResource(
        course_id=3,
        activity_id=17,
        section_name="Week 1",
        name="Project brief",
        resource_type="file",
        url="https://moodle.vut.cz/mod/resource/view.php?id=17",
        files=[
            MoodleFile(
                name="brief.pdf",
                url="https://moodle.vut.cz/pluginfile.php/17/brief.pdf",
                size_bytes=2048,
                mimetype="application/pdf",
            )
        ],
    )

    assert resource.model_dump(mode="json") == {
        "course_id": 3,
        "activity_id": 17,
        "section_name": "Week 1",
        "name": "Project brief",
        "resource_type": "file",
        "url": "https://moodle.vut.cz/mod/resource/view.php?id=17",
        "target_url": None,
        "files": [
            {
                "name": "brief.pdf",
                "url": "https://moodle.vut.cz/pluginfile.php/17/brief.pdf",
                "size_bytes": 2048,
                "mimetype": "application/pdf",
                "modified_at": None,
            }
        ],
    }

    with pytest.raises(ValueError):
        resource.name = "Replacement"


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


@pytest.mark.asyncio
async def test_assignment_file_content_requires_exact_listed_url_and_is_not_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = MoodleFile(
        name="brief.txt",
        url="https://moodle.vut.cz/pluginfile.php/17/brief.txt",
    )

    class FakeTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        async def download_file(self, url: str, *, max_bytes: int) -> tuple[bytes, str]:
            self.calls.append((url, max_bytes))
            return b"Moodle brief", "text/plain"

    transport = FakeTransport()
    client = MoodleClient(
        _settings(moodle_access_mode="web"),
        cache_store=CacheStore(tmp_path / "cache.sqlite3"),
        transport=transport,  # type: ignore[arg-type]
    )

    async def listed_files(assignment_id: int, *, force_refresh: bool = False) -> list[MoodleFile]:
        assert assignment_id == 17
        assert force_refresh is False
        return [file]

    monkeypatch.setattr(client, "get_assignment_files", listed_files)

    with pytest.raises(MoodleContentError, match="not listed"):
        await client.get_assignment_file_content(17, "https://moodle.vut.cz/pluginfile.php/17/other.txt")

    first = await client.get_assignment_file_content(17, file.url)
    second = await client.get_assignment_file_content(17, file.url)

    assert first.text == second.text == "Moodle brief"
    assert transport.calls == [(file.url, 8 * 1024 * 1024), (file.url, 8 * 1024 * 1024)]


@pytest.mark.asyncio
@pytest.mark.parametrize("max_characters", [0, 50_001, True, "20"])
async def test_assignment_file_content_enforces_character_limit(
    tmp_path: Path,
    max_characters: object,
) -> None:
    client = MoodleClient(_settings(), cache_store=CacheStore(tmp_path / "cache.sqlite3"))

    with pytest.raises(MoodleContentError, match="character limit"):
        await client.get_assignment_file_content(
            17,
            "https://moodle.vut.cz/pluginfile.php/17/brief.txt",
            max_characters=max_characters,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_web_course_resources_only_enrich_file_and_folder_activities(tmp_path: Path) -> None:
    course = MoodleCourse(
        id=42,
        name="Algorithms",
        url="https://moodle.vut.cz/course/view.php?id=42",
    )

    class FakeTransport:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def get_response(self, url: str) -> SimpleNamespace:
            self.calls.append(url)
            pages = {
                course.url: """
                    <section class='section'>
                      <h3>Week 1</h3>
                      <div class='activity'><a href='/mod/resource/view.php?id=101'>Brief</a></div>
                      <div class='activity'><a href='/mod/folder/view.php?id=102'>Examples</a></div>
                      <div class='activity'><a href='/mod/page/view.php?id=103'>Overview</a></div>
                      <div class='activity'><a href='/mod/url/view.php?id=104'>Site</a></div>
                      <div class='activity'><a href='/mod/forum/view.php?id=105'>Forum</a></div>
                    </section>
                """,
                "https://moodle.vut.cz/mod/resource/view.php?id=101": (
                    "<a href='/pluginfile.php/7/mod_resource/content/1/brief.pdf'>brief.pdf</a>"
                ),
                "https://moodle.vut.cz/mod/folder/view.php?id=102": (
                    "<a href='/pluginfile.php/7/mod_folder/content/0/example.pdf'>example.pdf</a>"
                ),
                "https://moodle.vut.cz/mod/url/view.php?id=104": (
                    "<main><a href='https://slides.example/lecture-7'>Lecture 7</a></main>"
                ),
            }
            return SimpleNamespace(text=pages[url], url=url)

    transport = FakeTransport()
    client = MoodleClient(
        _settings(moodle_access_mode="web"),
        cache_store=CacheStore(tmp_path / "cache.sqlite3"),
        transport=transport,  # type: ignore[arg-type]
    )

    async def courses(*, force_refresh: bool = False) -> list[MoodleCourse]:
        assert force_refresh is False
        return [course]

    client.get_courses = courses  # type: ignore[method-assign]

    resources = await client.get_course_resources(42)

    assert [resource.resource_type for resource in resources] == [
        "file",
        "folder",
        "page",
        "url",
        "unknown",
    ]
    assert [file.name for resource in resources for file in resource.files] == [
        "brief.pdf",
        "example.pdf",
    ]
    assert resources[3].target_url == "https://slides.example/lecture-7"
    assert transport.calls == [
        course.url,
        "https://moodle.vut.cz/mod/resource/view.php?id=101",
        "https://moodle.vut.cz/mod/folder/view.php?id=102",
        "https://moodle.vut.cz/mod/url/view.php?id=104",
    ]


@pytest.mark.asyncio
async def test_course_resources_reject_unknown_course_without_loading_a_page(
    tmp_path: Path,
) -> None:
    client = MoodleClient(_settings(), cache_store=CacheStore(tmp_path / "cache.sqlite3"))

    async def courses(*, force_refresh: bool = False) -> list[MoodleCourse]:
        return []

    client.get_courses = courses  # type: ignore[method-assign]

    with pytest.raises(MoodleDataError, match="course 42 was not found"):
        await client.get_course_resources(42)


@pytest.mark.asyncio
async def test_api_course_resources_map_metadata_without_exposing_api_tokens(
    tmp_path: Path,
) -> None:
    course = MoodleCourse(
        id=42,
        name="Algorithms",
        url="https://moodle.vut.cz/course/view.php?id=42",
    )

    class FakeApi:
        def __init__(self) -> None:
            self.course_ids: list[int] = []

        async def get_course_contents(self, course_id: int) -> list[dict[str, object]]:
            self.course_ids.append(course_id)
            return [
                {
                    "name": "Week 1",
                    "modules": [
                        {
                            "id": 101,
                            "name": "Brief",
                            "modname": "resource",
                            "contents": [
                                {
                                    "filename": "brief.pdf",
                                    "fileurl": (
                                        "https://moodle.vut.cz/webservice/pluginfile.php/7/"
                                        "mod_resource/content/1/brief.pdf?token=secret"
                                    ),
                                    "filesize": 2048,
                                    "mimetype": "application/pdf",
                                }
                            ],
                        },
                        {"id": 105, "name": "Forum", "modname": "forum", "contents": []},
                    ],
                }
            ]

    api = FakeApi()
    client = MoodleClient(
        _settings(moodle_access_mode="api", moodle_token="test-token"),
        cache_store=CacheStore(tmp_path / "cache.sqlite3"),
    )

    async def courses(*, force_refresh: bool = False) -> list[MoodleCourse]:
        return [course]

    client.get_courses = courses  # type: ignore[method-assign]
    client._api = lambda: api  # type: ignore[method-assign]

    resources = await client.get_course_resources(42)

    assert api.course_ids == [42]
    assert [(item.activity_id, item.resource_type) for item in resources] == [
        (101, "file"),
        (105, "unknown"),
    ]
    assert resources[0].url == "https://moodle.vut.cz/mod/resource/view.php?id=101"
    assert resources[0].files[0].url == (
        "https://moodle.vut.cz/pluginfile.php/7/mod_resource/content/1/brief.pdf"
    )
    assert "token" not in resources[0].files[0].url


@pytest.mark.asyncio
async def test_web_course_resource_limits_stop_before_activity_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course = MoodleCourse(
        id=42,
        name="Algorithms",
        url="https://moodle.vut.cz/course/view.php?id=42",
    )

    class FakeTransport:
        calls: list[str] = []

        async def get_response(self, url: str) -> SimpleNamespace:
            self.calls.append(url)
            return SimpleNamespace(text="", url=url)

    transport = FakeTransport()
    client = MoodleClient(
        _settings(moodle_access_mode="web"),
        cache_store=CacheStore(tmp_path / "cache.sqlite3"),
        transport=transport,  # type: ignore[arg-type]
    )

    async def courses(*, force_refresh: bool = False) -> list[MoodleCourse]:
        return [course]

    client.get_courses = courses  # type: ignore[method-assign]
    from vut_moodle import client as client_module
    from vut_moodle.models import MoodleCourseResource

    monkeypatch.setattr(
        client_module,
        "parse_course_resources",
        lambda _html, **_kwargs: [
            MoodleCourseResource(
                course_id=42,
                activity_id=index,
                name=f"Resource {index}",
                resource_type="file",
                url=f"https://moodle.vut.cz/mod/resource/view.php?id={index}",
            )
            for index in range(1, 302)
        ],
    )

    with pytest.raises(MoodleDataError, match="activity limit"):
        await client.get_course_resources(42)

    assert transport.calls == [course.url]


@pytest.mark.asyncio
async def test_course_resource_cache_is_separated_by_access_mode_and_course(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    course = MoodleCourse(
        id=42,
        name="Algorithms",
        url="https://moodle.vut.cz/course/view.php?id=42",
    )
    web_client = MoodleClient(
        _settings(moodle_access_mode="web", cache_path=cache_path),
    )
    api_client = MoodleClient(
        _settings(moodle_access_mode="api", moodle_token="test-token", cache_path=cache_path),
    )
    calls: list[str] = []

    async def courses(*, force_refresh: bool = False) -> list[MoodleCourse]:
        return [course]

    async def web_resources(_course: MoodleCourse) -> list[MoodleCourseResource]:
        calls.append("web")
        return []

    async def api_resources(_course: MoodleCourse) -> list[MoodleCourseResource]:
        calls.append("api")
        return []

    web_client.get_courses = courses  # type: ignore[method-assign]
    api_client.get_courses = courses  # type: ignore[method-assign]
    web_client._fetch_course_resources = web_resources  # type: ignore[method-assign]
    api_client._fetch_course_resources = api_resources  # type: ignore[method-assign]

    assert await web_client.get_course_resources(42) == []
    assert await web_client.get_course_resources(42) == []
    assert await api_client.get_course_resources(42) == []
    assert calls == ["web", "api"]
