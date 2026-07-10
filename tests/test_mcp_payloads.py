import json
from datetime import date

import pytest

from vut_mcp import server
from vut_mcp.payloads import course_points_payload
from vut_moodle.models import (
    MoodleAssignment,
    MoodleCourseResource,
    MoodleFile,
    MoodleFileContent,
)
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
