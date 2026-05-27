from datetime import date

from vut_mcp.payloads import course_points_payload
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

