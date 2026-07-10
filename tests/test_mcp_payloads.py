import json
from datetime import date

import pytest

from vut_mcp import server
from vut_mcp.payloads import course_points_payload
from vut_moodle.models import MoodleAssignment, MoodleFile
from vut_studis import Grade, GradeValue


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

    monkeypatch.setattr(server, "get_moodle_client", FakeMoodleClient)

    assignments = await server.vut_get_moodle_assignments()
    files = await server.vut_get_moodle_assignment_files(17)

    assert json.loads(json.dumps([item.model_dump(mode="json") for item in assignments]))
    assert json.loads(json.dumps([item.model_dump(mode="json") for item in files]))
