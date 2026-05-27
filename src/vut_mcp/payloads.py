from typing import Any

from vut_studis import Grade

COURSE_POINTS_FIELDS = {
    "course_code",
    "course_name",
    "points",
    "grade",
    "grade_awarded_on",
    "credit_awarded",
    "credit_awarded_on",
    "academic_year",
    "semester",
}


def course_points_payload(grade: Grade) -> dict[str, Any]:
    return grade.model_dump(mode="json", include=COURSE_POINTS_FIELDS)

