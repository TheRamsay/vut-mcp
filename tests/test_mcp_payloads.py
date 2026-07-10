import asyncio
import json
from datetime import date, datetime

import pytest

from vut_mcp import server
from vut_mcp.payloads import course_points_payload
from vut_moodle.models import (
    MoodleAssignment,
    MoodleCourseResource,
    MoodleFile,
    MoodleFileContent,
)
from vut_studis import CourseUpdate, CourseUpdates, Grade, GradeValue
from vut_studis.models import AssessmentDashboard, AssessmentDashboardItem, ScheduleItem


def test_course_points_payload_is_json_ready() -> None:
    payload = course_points_payload(
        Grade(
            course_code="ABC",
            course_name="Test Course",
            points=91.5,
            grade=GradeValue.A,
            grade_awarded_on=date(2026, 5, 27),
            credit_awarded=True,
            credit_awarded_on=date(2026, 5, 20),
            academic_year="2025/2026",
            semester="Letní semestr",
        )
    )

    assert payload == {
        "course_code": "ABC",
        "course_name": "Test Course",
        "points": 91.5,
        "grade": "A",
        "grade_awarded_on": "2026-05-27",
        "credit_awarded": True,
        "credit_awarded_on": "2026-05-20",
        "academic_year": "2025/2026",
        "semester": "Letní semestr",
    }


@pytest.mark.asyncio
async def test_moodle_mcp_tools_return_json_serializable_models(monkeypatch) -> None:
    assignment = MoodleAssignment(
        id=17,
        course_id=42,
        name="Project",
        url="https://moodle.vut.cz/mod/assign/view.php?id=17",
        files=[MoodleFile(name="specification.pdf", url="https://moodle.vut.cz/pluginfile.php/17")],
    )
    resource = MoodleCourseResource(
        course_id=42,
        activity_id=18,
        section_name="Week 1",
        name="Course brief",
        resource_type="file",
        url="https://moodle.vut.cz/mod/resource/view.php?id=18",
        files=assignment.files,
    )

    class FakeMoodleClient:
        async def get_courses(self, *, force_refresh: bool):
            assert force_refresh is False
            return []

        async def get_assignments(self, *, course_id: int | None, force_refresh: bool):
            assert course_id is None
            assert force_refresh is False
            return [assignment]

        async def get_assignment_files(self, assignment_id: int, *, force_refresh: bool):
            assert assignment_id == 17
            assert force_refresh is False
            return assignment.files

        async def get_assignment_file_content(
            self,
            assignment_id: int,
            file_url: str,
            *,
            max_characters: int,
        ) -> MoodleFileContent:
            assert assignment_id == 17
            assert file_url == assignment.files[0].url
            assert max_characters == 12
            return MoodleFileContent(
                file=assignment.files[0],
                content_type="text/plain",
                text="Specification",
                text_truncated=True,
                bytes_downloaded=20,
                extractor="text",
            )

        async def get_course_resources(self, course_id: int, *, force_refresh: bool):
            assert course_id == 42
            assert force_refresh is True
            return [resource]

    monkeypatch.setattr(server, "get_moodle_client", FakeMoodleClient)

    assignments = await server.vut_get_moodle_assignments()
    files = await server.vut_get_moodle_assignment_files(17)
    content = await server.vut_get_moodle_assignment_file_content(
        17,
        assignment.files[0].url,
        max_characters=12,
    )
    resources = await server.vut_get_moodle_course_resources(42, force_refresh=True)

    assert json.loads(json.dumps([item.model_dump(mode="json") for item in assignments]))
    assert json.loads(json.dumps([item.model_dump(mode="json") for item in files]))
    assert json.loads(json.dumps(content.model_dump(mode="json"))) == {
        "file": {
            "name": "specification.pdf",
            "url": "https://moodle.vut.cz/pluginfile.php/17",
            "size_bytes": None,
            "mimetype": None,
            "modified_at": None,
        },
        "content_type": "text/plain",
        "text": "Specification",
        "text_truncated": True,
        "bytes_downloaded": 20,
        "extractor": "text",
    }
    assert json.loads(json.dumps([item.model_dump(mode="json") for item in resources])) == [
        {
            "course_id": 42,
            "activity_id": 18,
            "section_name": "Week 1",
            "name": "Course brief",
            "resource_type": "file",
            "url": "https://moodle.vut.cz/mod/resource/view.php?id=18",
            "target_url": None,
            "files": [
                {
                    "name": "specification.pdf",
                    "url": "https://moodle.vut.cz/pluginfile.php/17",
                    "size_bytes": None,
                    "mimetype": None,
                    "modified_at": None,
                }
            ],
        }
    ]


@pytest.mark.asyncio
async def test_get_agenda_fetches_sources_in_parallel_with_requested_freshness(
    monkeypatch,
) -> None:
    studis_started = asyncio.Event()
    moodle_started = asyncio.Event()
    calls: list[tuple[str, object, object]] = []
    expected_agenda = object()

    class FakeStudisClient:
        async def get_pending_actions(self, *, horizon_days: int, force_refresh: bool):
            calls.append(("studis", horizon_days, force_refresh))
            studis_started.set()
            await moodle_started.wait()
            return ["studis-action"]

    class FakeMoodleClient:
        async def get_assignments(self, *, course_id: int | None, force_refresh: bool):
            calls.append(("moodle", course_id, force_refresh))
            moodle_started.set()
            await studis_started.wait()
            return ["moodle-assignment"]

    def fake_build_agenda(
        *,
        pending_actions: list[str],
        moodle_assignments: list[str],
        horizon_days: int,
    ) -> object:
        assert pending_actions == ["studis-action"]
        assert moodle_assignments == ["moodle-assignment"]
        assert horizon_days == 30
        return expected_agenda

    monkeypatch.setattr(server, "get_studis_client", FakeStudisClient)
    monkeypatch.setattr(server, "get_moodle_client", FakeMoodleClient)
    monkeypatch.setattr(server, "build_agenda", fake_build_agenda)

    result = await asyncio.wait_for(
        server.vut_get_agenda(horizon_days=30, force_refresh=True),
        timeout=0.5,
    )

    assert result is expected_agenda
    assert sorted(calls) == [("moodle", None, True), ("studis", 30, True)]


@pytest.mark.asyncio
@pytest.mark.parametrize("horizon_days", [True, 0, 91])
async def test_get_agenda_rejects_invalid_horizon_without_obtaining_clients(
    monkeypatch,
    horizon_days: int,
) -> None:
    def unexpected_client_access() -> None:
        raise AssertionError("agenda validation must happen before obtaining clients")

    monkeypatch.setattr(server, "get_studis_client", unexpected_client_access)
    monkeypatch.setattr(server, "get_moodle_client", unexpected_client_access)

    with pytest.raises(ValueError, match="horizon_days must be between 1 and 90"):
        await server.vut_get_agenda(horizon_days=horizon_days)

@pytest.mark.asyncio
async def test_assessment_dashboard_mcp_tool_returns_json_serializable_model(monkeypatch) -> None:
    dashboard = AssessmentDashboard(
        generated_at=datetime(2026, 7, 10, 12, 0),
        horizon_days=30,
        include_past=False,
        items=[
            AssessmentDashboardItem(
                course_code="ABC",
                course_name="Test Course",
                name="First term",
                detail_url="https://www.vut.cz/studis/student.phtml?sn=termin_detail&tid=1",
            )
        ],
    )

    class FakeStudisClient:
        async def get_assessment_dashboard(
            self,
            *,
            horizon_days: int,
            include_past: bool,
            force_refresh: bool,
        ) -> AssessmentDashboard:
            assert horizon_days == 30
            assert include_past is False
            assert force_refresh is True
            return dashboard

    monkeypatch.setattr(server, "get_studis_client", FakeStudisClient)

    result = await server.vut_get_assessment_dashboard(force_refresh=True)

    assert json.loads(json.dumps(result.model_dump(mode="json"))) == {
        "generated_at": "2026-07-10T12:00:00",
        "horizon_days": 30,
        "include_past": False,
        "items": [
            {
                "course_code": "ABC",
                "course_name": "Test Course",
                "academic_year": None,
                "assessment_order": None,
                "assessment_name": None,
                "assessment_category": None,
                "term_number": None,
                "name": "First term",
                "note": None,
                "starts_at": None,
                "ends_at": None,
                "examiner": None,
                "room": None,
                "registered": None,
                "capacity_used": None,
                "capacity_total": None,
                "registration_info": None,
                "registration_opens_at": None,
                "registration_closes_at": None,
                "can_register": None,
                "can_unregister": None,
                "max_points": None,
                "earned_points": None,
                "detail_url": "https://www.vut.cz/studis/student.phtml?sn=termin_detail&tid=1",
            }
        ],
        "course_truncated_count": 0,
        "term_truncated_count": 0,
        "unavailable_course_codes": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("horizon_days", [0, 181])
async def test_assessment_dashboard_mcp_tool_validates_horizon_days(
    monkeypatch,
    horizon_days: int,
) -> None:
    monkeypatch.setattr(
        server,
        "get_studis_client",
        lambda: (_ for _ in ()).throw(AssertionError("client must not be called")),
    )

    with pytest.raises(ValueError, match="between 1 and 180"):
        await server.vut_get_assessment_dashboard(horizon_days=horizon_days)

@pytest.mark.asyncio
async def test_schedule_mcp_preserves_date_filters_and_serializes_schedule_dates(
    monkeypatch,
) -> None:
    requested_from = date(2026, 5, 20)
    requested_to = date(2026, 5, 21)
    item = ScheduleItem(
        course_name="Lecture",
        starts_at=datetime(2026, 5, 20, 9),
        ends_at=datetime(2026, 5, 20, 10),
    )

    class FakeStudisClient:
        async def get_schedule(self, *, date_from: date | None, date_to: date | None):
            assert date_from is requested_from
            assert date_to is requested_to
            return [item]

    monkeypatch.setattr(server, "get_studis_client", FakeStudisClient)

    result = await server.vut_get_schedule(requested_from, requested_to)

    assert requested_from == date(2026, 5, 20)
    assert requested_to == date(2026, 5, 21)
    payload = json.loads(
        json.dumps([schedule_item.model_dump(mode="json") for schedule_item in result])
    )
    assert payload[0]["course_name"] == "Lecture"
    assert payload[0]["starts_at"] == "2026-05-20T09:00:00"
    assert payload[0]["ends_at"] == "2026-05-20T10:00:00"

@pytest.mark.asyncio
async def test_course_updates_mcp_tool_returns_json_serializable_metadata(monkeypatch) -> None:
    updates = CourseUpdates(
        items=[
            CourseUpdate(
                id="update-1",
                published_at=date(2026, 7, 10),
                title="Example update",
                course_code="ABC",
                course_name="Test Course",
                author="Example Teacher",
                url="https://www.vut.cz/studis/student.phtml?sn=aktualita_detail&id=1",
                course_url="https://www.vut.cz/studis/student.phtml?sn=predmet_detail&apid=1",
            )
        ]
    )

    class FakeStudisClient:
        async def get_course_updates(self, *, limit: int, force_refresh: bool) -> CourseUpdates:
            assert limit == 1
            assert force_refresh is True
            return updates

    monkeypatch.setattr(server, "get_studis_client", FakeStudisClient)

    result = await server.vut_get_course_updates(limit=1, force_refresh=True)

    assert json.loads(json.dumps(result.model_dump(mode="json"))) == {
        "items": [
            {
                "id": "update-1",
                "published_at": "2026-07-10T00:00:00",
                "title": "Example update",
                "course_code": "ABC",
                "course_name": "Test Course",
                "author": "Example Teacher",
                "url": "https://www.vut.cz/studis/student.phtml?sn=aktualita_detail&id=1",
                "course_url": "https://www.vut.cz/studis/student.phtml?sn=predmet_detail&apid=1",
            }
        ],
        "truncated_count": 0,
    }
